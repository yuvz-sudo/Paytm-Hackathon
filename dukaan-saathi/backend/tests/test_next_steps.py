"""Settlement explainer + chargebacks, UPI fee (MDR) estimate, quiet-hour offers, payment verification."""
from datetime import datetime, timedelta

import pytest

from app import clock
from app.models import Chargeback, Outbox, Settlement, SettlementLine, Transaction
from app.services import actions, customers, fees, payments, settlements
from tests.conftest import H


def M(db, i=1):
    from app.models import Merchant
    return db.get(Merchant, i)


# ---------------------------------------------------------------- 1. settlement explainer
def test_every_settlement_adds_up(db):
    rows = db.query(Settlement).all()
    assert rows
    for s in rows:
        lines = db.query(SettlementLine).filter_by(settlement_id=s.id).all()
        gross = settlements.explain(db, M(db, s.merchant_id), s.id)["gross"]
        assert gross == pytest.approx(s.amount + sum(l.amount for l in lines), abs=0.01)


def test_explain_lists_each_deduction_and_net(client):
    sid = next(x["id"] for x in client.get("/api/settlements", headers=H()).json()["recent"])
    r = client.get(f"/api/settlements/{sid}/explain", headers=H()).json()
    assert r["net"] == pytest.approx(r["gross"] - r["total_deductions"], abs=0.01)
    assert r["summary"] and (not r["deductions"] or all(d["amount"] > 0 for d in r["deductions"]))


def test_explain_includes_gst_on_commission(db):
    ex = [settlements.explain(db, M(db), s.id) for s in db.query(Settlement).filter_by(merchant_id=1)]
    withcomm = [e for e in ex if any(d["kind"] == "commission" for d in e["deductions"])]
    assert withcomm
    for e in withcomm:
        c = next(d["amount"] for d in e["deductions"] if d["kind"] == "commission")
        g = next(d["amount"] for d in e["deductions"] if d["kind"] == "gst")
        assert g == pytest.approx(c * 0.18, abs=0.02)


def test_explain_unknown_or_foreign_settlement_is_404(client, db):
    other = db.query(Settlement).filter_by(merchant_id=2).first().id
    assert client.get("/api/settlements/999999/explain", headers=H()).status_code == 404
    assert client.get(f"/api/settlements/{other}/explain", headers=H()).status_code == 404


def test_explain_without_breakdown_is_gross_equals_net(db):
    s = db.query(Settlement).filter_by(merchant_id=1).first()
    db.query(SettlementLine).filter_by(settlement_id=s.id).delete()
    db.commit()
    e = settlements.explain(db, M(db), s.id)
    assert e["gross"] == e["net"] and e["has_breakdown"] is False


def test_failed_settlement_explains_the_failure(db):
    s = db.query(Settlement).filter_by(merchant_id=1, status="failed").first()
    assert "inactive" in settlements.explain(db, M(db), s.id)["summary"]


def test_chargeback_seeded_with_deadline_and_urgent(client):
    c = client.get("/api/chargebacks", headers=H()).json()
    op = [x for x in c["chargebacks"] if x["status"] == "open"]
    assert len(op) == 1 and op[0]["days_left"] == 2 and op[0]["urgent"] is True
    assert c["open_count"] == 1 and c["urgent_count"] == 1


def test_chargeback_empty_state_for_merchant_without_any(client):
    c = client.get("/api/chargebacks", headers=H(2)).json()
    assert c["no_data"] is True and c["chargebacks"] == []
    assert client.post("/api/chargebacks/proof", json={}, headers=H(2)).status_code == 400


def test_chargeback_proof_needs_approval_then_sends_once(client, db):
    r = client.post("/api/chargebacks/proof", json={}, headers=H()).json()
    assert db.query(Outbox).count() == 0  # nothing leaves before approval
    aid = r["action"]["id"]
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).json()["status"] == "executed"
    assert db.query(Outbox).filter_by(to_name="Paytm Disputes").count() == 1
    assert db.query(Chargeback).filter_by(merchant_id=1, status="proof_sent").count() == 1
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).status_code == 409
    assert client.post("/api/chargebacks/proof", json={}, headers=H()).status_code == 400  # none left open


def test_chargeback_proof_revalidated_after_deadline(client, db):
    aid = client.post("/api/chargebacks/proof", json={}, headers=H()).json()["action"]["id"]
    cb = db.query(Chargeback).filter_by(merchant_id=1, status="open").first()
    cb.proof_due_date = clock.today() - timedelta(days=1)  # deadline slips past while the draft waits for approval
    db.commit()
    r = client.post(f"/api/actions/{aid}/approve", headers=H())
    assert r.status_code == 200 and r.json()["status"] == "failed" and db.query(Outbox).count() == 0


def test_chargeback_proof_cannot_target_other_merchants_chargeback(client, db):
    cb = db.query(Chargeback).filter_by(merchant_id=1, status="open").first().id
    assert client.post("/api/chargebacks/proof", json={"chargeback_id": cb}, headers=H(2)).status_code == 404


def test_overdue_chargeback_cannot_be_drafted(client, db):
    cb = db.query(Chargeback).filter_by(merchant_id=1, status="open").first()
    cb.proof_due_date = clock.today() - timedelta(days=1)
    db.commit()
    assert client.post("/api/chargebacks/proof", json={}, headers=H()).status_code == 409
    rows = client.get("/api/chargebacks", headers=H()).json()["chargebacks"]
    assert next(x for x in rows if x["id"] == cb.id)["overdue"] is True


def test_urgent_chargeback_is_in_briefing(client):
    b = client.get("/api/briefing", headers=H()).json()
    card = next(c for c in b["cards"] if c["id"] == "chargeback")
    assert card["severity"] == "high" and "chargeback" in b["script"].lower()
    assert not any(c["id"] == "chargeback" for c in client.get("/api/briefing", headers=H(2)).json()["cards"])


def test_chargeback_endpoints_respect_consent(client):
    client.put("/api/consent/transactions", json={"granted": False}, headers=H())
    assert client.get("/api/chargebacks", headers=H()).status_code == 403
    assert client.get("/api/settlements/1/explain", headers=H()).status_code == 403


@pytest.mark.parametrize("q", ["payout kam kyun aaya", "why did I get less money in my bank", "settlement mein paisa kyun kata"])
def test_chat_explains_payout(client, q):
    r = client.post("/api/chat", json={"message": q}, headers=H()).json()
    assert r["engine"] != "error" and ("Paytm" in r["reply"] or "payout" in r["reply"].lower())
    assert "explain_settlement" in str(r)


def test_chat_chargeback_flow(client, db):
    assert "chargeback" in client.post("/api/chat", json={"message": "chargeback ka kya hai"}, headers=H()).json()["reply"].lower()
    r = client.post("/api/chat", json={"message": "chargeback ka proof bhejo", "session_id": "s1"}, headers=H()).json()
    assert db.query(Outbox).count() == 0
    r2 = client.post("/api/chat", json={"message": "haan bhej do", "session_id": "s1"}, headers=H()).json()
    assert db.query(Outbox).filter_by(to_name="Paytm Disputes").count() == 1, (r, r2)


def test_sales_why_question_is_not_hijacked_by_payout_rule(client):
    r = client.post("/api/chat", json={"message": "kal sales kam kyu hui"}, headers=H()).json()
    assert "explain_settlement" not in str(r)


# ---------------------------------------------------------------- 2. UPI fee (MDR)
def _upi(db, amount, minutes_ago=60, mid=1, status="success"):
    db.add(Transaction(merchant_id=mid, ts=clock.now() - timedelta(minutes=minutes_ago), amount=amount, mode="UPI", status=status))


def _wipe_upi(db, mid=1):
    db.query(Transaction).filter_by(merchant_id=mid, mode="UPI").update({"mode": "CARD"})
    db.commit()


def test_mdr_zero_under_monthly_exemption(db):
    _wipe_upi(db)
    _upi(db, 5000)
    _upi(db, 90_000)
    db.commit()
    r = fees.mdr_estimate(db, M(db), "this_month")
    assert r["estimated_mdr"] == 0 and r["chargeable_amount"] == 0 and r["estimate"] is True


def test_mdr_charged_above_exemption_and_capped(db):
    _wipe_upi(db)
    for a in (1500, 2000, 2500, 120_000):  # >1 lakh in month; only 2500 and 120000 exceed Rs 2000
        _upi(db, a)
    db.commit()
    r = fees.mdr_estimate(db, M(db), "this_month")
    assert r["chargeable_count"] == 2
    assert r["estimated_mdr"] == pytest.approx(2500 * 0.004 + 300)  # second payment hits the Rs 300 cap
    assert r["share_charged_pct"] == pytest.approx(122_500 / 126_000 * 100, abs=0.1)


def test_mdr_ignores_failed_and_non_upi(db):
    _wipe_upi(db)
    _upi(db, 150_000, status="failed")
    db.commit()
    assert fees.mdr_estimate(db, M(db), "this_month")["no_data"] is True


def test_mdr_endpoint_has_assumptions_and_empty_state(client):
    r = client.get("/api/fees/mdr?period=last_30_days", headers=H()).json()
    assert r["estimate"] and len(r["assumptions"]) >= 3
    assert client.get("/api/fees/mdr?period=today", headers=H(3)).json()["no_data"] in (True, False)


@pytest.mark.parametrize("q", ["MDR kya hai", "UPI fee lagega?", "upi par charge kitna"])
def test_chat_mdr(client, q):
    r = client.post("/api/chat", json={"message": q}, headers=H()).json()
    assert "estimate" in r["reply"].lower() or "anumaan" in r["reply"].lower() or "fee" in r["reply"].lower()


# ---------------------------------------------------------------- 3. quiet-hour offers
def test_winback_offer_is_timed_to_a_quiet_hour(client):
    r = client.post("/api/customers/winback", json={"discount_pct": 10}, headers=H()).json()
    w = r["window"]
    assert w and 0 <= w["start_hour"] < w["end_hour"] <= 24 and w["when"] in ("today", "tomorrow")
    assert w["label"] in r["action"]["payload"]["message"]
    hp = client.get("/api/sales/hours", headers=H()).json()
    assert w["start_hour"] in (hp["slow_hours"] or hp["quietest_hours"])


def test_winback_keeps_discount_cap_with_window(client):
    r = client.post("/api/customers/winback", json={"discount_pct": 90}, headers=H()).json()
    assert r["discount_capped"] and r["discount_pct"] == r["cap_pct"] and r["window"]


def test_winback_explicit_hour_and_validation(client):
    r = client.post("/api/customers/winback", json={"discount_pct": 10, "send_hour": 15}, headers=H()).json()
    assert r["window"]["start_hour"] == 15 and r["window"]["source"] == "chosen_by_merchant"
    assert client.post("/api/customers/winback", json={"send_hour": 25}, headers=H()).status_code == 422


def test_winback_without_hourly_data_has_no_window(client):
    client.put("/api/consent/transactions", json={"granted": False}, headers=H())
    r = client.post("/api/customers/winback", json={"discount_pct": 10}, headers=H()).json()
    assert r["window"] is None and " between " not in r["action"]["payload"]["message"]


def test_customers_summary_suggests_window(client):
    assert client.get("/api/customers", headers=H()).json()["suggested_window"]["label"]


def test_next_quiet_hour_skips_hours_already_passed(db, monkeypatch):
    prof = {"no_data": False, "slow_hours": [8, 15], "quietest_hours": [8, 15], "peak_hours": [12]}
    monkeypatch.setattr("app.services.analytics.hourly_profile", lambda *a, **k: prof)
    monkeypatch.setenv("FAKE_NOW", "2026-11-14T09:30:00")
    assert customers.quiet_window(db, M(db))["start_hour"] == 15
    monkeypatch.setenv("FAKE_NOW", "2026-11-14T16:00:00")
    w = customers.quiet_window(db, M(db))
    assert w["start_hour"] == 8 and w["when"] == "tomorrow"


# ---------------------------------------------------------------- 4. counter-fraud nudge
def test_verify_finds_recent_payment(client, db):
    _upi(db, 777, minutes_ago=2)
    db.commit()
    r = client.get("/api/payments/verify?amount=777&minutes=5", headers=H()).json()
    assert r["received"] is True and r["matches"][0]["minutes_ago"] == 2 and r["helpline"] == "1930"


def test_verify_says_no_for_old_payment_failed_payment_and_unknown_amount(client, db):
    _upi(db, 888, minutes_ago=30)
    _upi(db, 999, minutes_ago=1, status="failed")
    db.commit()
    assert client.get("/api/payments/verify?amount=888&minutes=5", headers=H()).json()["verdict"] == "earlier_only"
    f = client.get("/api/payments/verify?amount=999&minutes=5", headers=H()).json()
    assert f["received"] is False and f["verdict"] == "not_received_failed"
    assert client.get("/api/payments/verify?amount=123456", headers=H()).json()["verdict"] == "not_found"


def test_verify_is_scoped_to_the_merchant(client, db):
    _upi(db, 4321, minutes_ago=1, mid=2)
    db.commit()
    assert client.get("/api/payments/verify?amount=4321", headers=H(1)).json()["received"] is False
    assert client.get("/api/payments/verify?amount=4321", headers=H(2)).json()["received"] is True


@pytest.mark.parametrize("qs", ["amount=0", "amount=-5", "amount=abc", "amount=100&minutes=0", "amount=100&minutes=500", ""])
def test_verify_rejects_bad_input(client, qs):
    assert client.get(f"/api/payments/verify?{qs}", headers=H()).status_code == 422


def test_chat_verify_payment(client, db):
    _upi(db, 640, minutes_ago=1)
    db.commit()
    yes = client.post("/api/chat", json={"message": "payment aaya 640?"}, headers=H()).json()["reply"]
    assert "1930" in yes and yes.lower().startswith(("yes", "haan"))
    no = client.post("/api/chat", json={"message": "customer ne 641 ka screenshot dikhaya"}, headers=H()).json()["reply"]
    assert "1930" in no and not no.lower().startswith(("yes", "haan"))
    ask = client.post("/api/chat", json={"message": "customer ne screenshot dikhaya"}, headers=H()).json()["reply"]
    assert "amount" in ask.lower() or "kitna" in ask.lower()


def test_verify_respects_consent(client):
    client.put("/api/consent/transactions", json={"granted": False}, headers=H())
    assert client.get("/api/payments/verify?amount=100", headers=H()).status_code == 403


# ---------------------------------------------------------------- growth advisor + dashboard comparison
def test_compare_week_and_month(client):
    c = client.get("/api/sales/compare", headers=H()).json()
    assert c["week"]["current"] > 0 and c["week"]["previous"] > 0 and c["week"]["change_pct"] is not None
    assert c["month"]["current"] > 0


def test_compare_on_first_of_month_has_no_month(client, monkeypatch):
    monkeypatch.setenv("FAKE_NOW", "2026-12-01T09:30:00")
    assert client.get("/api/sales/compare", headers=H()).json()["month"] is None


def test_growth_advisor_ranked_with_numbers(client):
    g = client.get("/api/growth/advisor", headers=H()).json()
    assert g["opportunities"] and g["biggest_problem"]
    imp = [o["est_monthly_impact"] for o in g["opportunities"]]
    assert imp == sorted(imp, reverse=True)
    ats = [p["at_stake"] or 0 for p in g["problems"]]
    assert ats == sorted(ats, reverse=True) and g["problems"][0] == g["biggest_problem"]
    assert all(o["detail"] for o in g["opportunities"])


def test_growth_advisor_empty_state_without_history(client):
    from tests.test_auth import onboard_body, signup
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    g = client.get("/api/growth/advisor", headers=h).json()
    assert g["no_data"] is True and g["opportunities"] == []
    assert client.get("/api/sales/compare", headers=h).json()["no_data"] is True


def test_growth_respects_consent(client):
    client.put("/api/consent/transactions", json={"granted": False}, headers=H())
    assert client.get("/api/growth/advisor", headers=H()).status_code == 403
    assert client.get("/api/sales/compare", headers=H()).status_code == 403


def test_chat_growth_and_compare_offline(client):
    r = client.post("/api/chat", json={"message": "how can I increase my sales this week?"}, headers=H()).json()
    assert "get_growth_advice" in str(r["tools"]) or r["engine"] == "llm"
    r = client.post("/api/chat", json={"message": "compare this week vs last week sales"}, headers=H()).json()
    assert r["reply"]


def test_sales_dip_card_gives_a_reason(client, db):
    from app.models import Transaction
    y = clock.today() - timedelta(days=1)
    db.query(Transaction).filter(Transaction.merchant_id == 1, Transaction.ts >= datetime(y.year, y.month, y.day),
                                 Transaction.ts < datetime(y.year, y.month, y.day) + timedelta(days=1),
                                 Transaction.id % 10 < 7).update({"status": "failed"}, synchronize_session=False)
    db.commit()
    cards = client.get("/api/briefing?refresh=true", headers=H()).json()["cards"]
    drop = [c for c in cards if c["id"] == "sales_drop"]
    assert drop and "Mainly" in drop[0]["detail"]


# ---------------------------------------------------------------- LLM cost guards (no real API calls)
def _fake_llm(monkeypatch, calls):
    from app.agent import llm

    def fake_chat(ctx, history, text):
        calls.append(text)
        from app.services import llm_budget
        llm_budget.record(ctx.db, ctx.merchant.id, "chat", 1, 100)
        return "LLM answer"
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", fake_chat)


def test_llm_budget_exhausted_falls_back_to_rules(client, monkeypatch):
    from app import config
    calls = []
    _fake_llm(monkeypatch, calls)
    monkeypatch.setattr(config, "LLM_DAILY_REQUESTS", 2)
    engines = [client.post("/api/chat", json={"message": "kal ki sales"}, headers=H()).json()["engine"] for _ in range(4)]
    assert engines == ["llm", "llm", "rules", "rules"] and len(calls) == 2
    u = client.get("/api/llm/usage", headers=H()).json()
    assert u["requests"] == 2 and u["remaining"] == 0 and u["limit"] == 2


def test_budget_is_per_merchant(client, monkeypatch):
    from app import config
    _fake_llm(monkeypatch, [])
    monkeypatch.setattr(config, "LLM_DAILY_REQUESTS", 1)
    assert client.post("/api/chat", json={"message": "kal ki sales"}, headers=H(1)).json()["engine"] == "llm"
    assert client.post("/api/chat", json={"message": "kal ki sales"}, headers=H(1)).json()["engine"] == "rules"
    assert client.post("/api/chat", json={"message": "kal ki sales"}, headers=H(2)).json()["engine"] == "llm"


def test_rules_first_mode_spares_the_llm_for_routine_questions(client, monkeypatch):
    from app import config
    calls = []
    _fake_llm(monkeypatch, calls)
    monkeypatch.setattr(config, "LLM_MODE", "rules_first")
    assert client.post("/api/chat", json={"message": "kal ki sales"}, headers=H()).json()["engine"] == "rules"
    assert calls == []
    client.post("/api/chat", json={"message": "mera dukaan kaisa chal raha hai overall, thoda detail mein samjhao"}, headers=H())
    assert len(calls) == 1


def test_approvals_never_use_the_llm(client, monkeypatch):
    # the proposal is made by the rule engine (LLM off), then the LLM is switched on: the "yes" must still not reach it
    client.post("/api/chat", json={"message": "order kar do", "session_id": "z"}, headers=H())
    calls = []
    _fake_llm(monkeypatch, calls)
    r = client.post("/api/chat", json={"message": "haan bhej do", "session_id": "z"}, headers=H()).json()
    assert calls == [] and r["engine"] == "rules"


# ---------------------------------------------------------------- marketing studio
def _mk(client, **kw):
    body = {"occasion": "Diwali", "discount_pct": 10, "valid_days": 7, "audience": "lapsed", "use_llm": False, **kw}
    return client.post("/api/marketing/campaigns", json=body, headers=H())


def test_campaign_is_drafted_not_sent(client, db):
    r = _mk(client).json()
    assert r["campaign"]["status"] == "draft" and r["campaign"]["recipient_count"] > 0 and r["action"]["kind"] == "campaign_send"
    assert db.query(Outbox).count() == 0
    assert "{name}" in r["campaign"]["message"] and "10%" in r["campaign"]["message"]


def test_campaign_discount_capped(client):
    r = _mk(client, discount_pct=90).json()
    assert r["discount_capped"] and r["campaign"]["discount_pct"] == r["cap_pct"]


def test_campaign_approval_sends_once_and_marks_sent(client, db):
    r = _mk(client).json()
    ok = client.post(f"/api/actions/{r['action']['id']}/approve", headers=H()).json()
    assert ok["status"] == "executed" and db.query(Outbox).count() == r["campaign"]["recipient_count"]
    c = client.get("/api/marketing/campaigns", headers=H()).json()["campaigns"][0]
    assert c["status"] == "sent" and c["performance"]["recipients"] == r["campaign"]["recipient_count"]
    assert client.post(f"/api/actions/{r['action']['id']}/approve", headers=H()).status_code == 409


def test_campaign_skips_do_not_contact(client, db):
    from app.models import Customer
    r = _mk(client).json()
    first = db.query(Customer).filter_by(id=r["action"]["payload"]["recipients"][0]["id"]).first()
    first.do_not_contact = True
    db.commit()
    client.post(f"/api/actions/{r['action']['id']}/approve", headers=H())
    assert db.query(Outbox).filter_by(to_name=first.name).count() == 0


def test_campaign_rejected_shows_rejected(client):
    r = _mk(client).json()
    client.post(f"/api/actions/{r['action']['id']}/reject", headers=H())
    assert client.get("/api/marketing/campaigns", headers=H()).json()["campaigns"][0]["status"] == "rejected"


def test_campaign_validation_and_empty_states(client):
    assert client.post("/api/marketing/campaigns", json={"occasion": "x", "audience": "nope"}, headers=H()).status_code == 422
    assert client.post("/api/marketing/campaigns", json={"occasion": "", "discount_pct": 5}, headers=H()).status_code == 422
    from tests.test_auth import onboard_body, signup
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    assert client.get("/api/marketing/campaigns", headers=h).json()["no_data"] is True
    assert client.post("/api/marketing/campaigns", json={"occasion": "Diwali"}, headers=h).status_code == 400


def test_campaign_llm_copy_guarded(client, monkeypatch):
    from app.agent import llm
    monkeypatch.setattr(llm, "write_copy", lambda *a, **k: "Hi {name}! Get 50% off now, visit http://evil.test")
    assert _mk(client, use_llm=True).json()["campaign"]["copy_source"] == "template"  # link and wrong discount rejected
    monkeypatch.setattr(llm, "write_copy", lambda *a, **k: "Namaste {name} ji! Diwali par 10% chhoot. 🙏")
    assert _mk(client, use_llm=True, discount_pct=10, occasion="Diwali2").json()["campaign"]["copy_source"] == "llm"


def test_campaign_is_scoped_and_consent_gated(client):
    r = _mk(client).json()
    assert client.post(f"/api/marketing/campaigns/{r['campaign']['id']}/poster", json={}, headers=H(2)).status_code == 404
    client.put("/api/consent/customers", json={"granted": False}, headers=H())
    assert client.get("/api/marketing/campaigns", headers=H()).status_code == 403


def test_poster_not_configured_and_limit(client, monkeypatch, db):
    from app import config
    from app.services import llm_budget
    cid = _mk(client).json()["campaign"]["id"]
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert client.post(f"/api/marketing/campaigns/{cid}/poster", json={}, headers=H()).status_code == 502
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    llm_budget.record(db, 1, "poster", 5, 0)
    assert client.post(f"/api/marketing/campaigns/{cid}/poster", json={}, headers=H()).status_code == 429


def test_poster_generated_once_then_cached(client, monkeypatch, tmp_path):
    import base64
    from app import config
    from app.services import marketing
    monkeypatch.setattr(config, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(marketing, "POSTER_DIR", tmp_path)
    calls = []

    class R:
        def raise_for_status(self): pass
        def json(self): return {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(b"png").decode()}}]}}]}
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (calls.append(1), R())[1])
    cid = _mk(client).json()["campaign"]["id"]
    a = client.post(f"/api/marketing/campaigns/{cid}/poster", json={}, headers=H()).json()
    b = client.post(f"/api/marketing/campaigns/{cid}/poster", json={}, headers=H()).json()
    assert a["image"].startswith("data:image/png") and b["cached"] is True and len(calls) == 1


def test_chat_campaign_request(client, db):
    r = client.post("/api/chat", json={"message": "Diwali ke liye meri shop ka ad banao", "session_id": "c1"}, headers=H()).json()
    assert "propose_campaign" in str(r["tools"]) and r["pending_actions"]
    assert db.query(Outbox).count() == 0


# ---------------------------------------------------------------- phase 3: retention segments
def test_segments_partition_customers_and_match_lapsed(client):
    s = client.get("/api/retention/segments", headers=H()).json()
    assert not s["no_data"] and [x["id"] for x in s["segments"]] == ["high_value", "repeat", "new", "at_risk", "lapsed"]
    assert sum(x["count"] for x in s["segments"]) + s["unsegmented"] == s["identified"]
    lapsed = client.get("/api/customers", headers=H()).json()["lapsed"]
    assert next(x for x in s["segments"] if x["id"] == "lapsed")["count"] == len(lapsed)
    assert all(m["usual_item"] is None or isinstance(m["usual_item"], str) for x in s["segments"] for m in x["members"])


def test_segments_empty_state_and_consent(client):
    from tests.test_auth import onboard_body, signup
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    assert client.get("/api/retention/segments", headers=h).json()["no_data"] is True
    assert client.post("/api/retention/offers", json={"segment": "lapsed"}, headers=h).status_code == 400
    client.put("/api/consent/customers", json={"granted": False}, headers=H())
    assert client.get("/api/retention/segments", headers=H()).status_code == 403


def test_segment_offer_is_personalised_capped_and_needs_approval(client, db):
    r = client.post("/api/retention/offers", json={"segment": "lapsed", "use_llm": False}, headers=H()).json()
    assert r["campaign"]["status"] == "draft" and r["campaign"]["discount_pct"] == 12 and db.query(Outbox).count() == 0
    recs = r["action"]["payload"]["recipients"]
    with_item = [x for x in recs if x["item"]]
    assert with_item and all(x["item"] in x["message"] for x in with_item) and all("{name}" not in x["message"] for x in recs)
    assert client.post("/api/retention/offers", json={"segment": "lapsed", "discount_pct": 90, "use_llm": False}, headers=H()).json()["discount_capped"] is True


def test_segment_offer_for_high_value_is_a_thank_you_without_discount(client):
    r = client.post("/api/retention/offers", json={"segment": "high_value", "use_llm": False}, headers=H()).json()
    msg = r["campaign"]["message"]
    assert r["campaign"]["discount_pct"] == 0 and ("dhanyawad" in msg.lower() or "thank" in msg.lower()) and "%" not in msg


def test_segment_offer_skips_do_not_contact_and_empty_segment(client, db):
    from app.models import Customer
    assert client.post("/api/retention/offers", json={"segment": "new", "use_llm": False}, headers=H()).status_code == 400  # none new for Ramesh
    r = client.post("/api/retention/offers", json={"segment": "repeat", "use_llm": False}, headers=H()).json()
    first = db.get(Customer, r["action"]["payload"]["recipients"][0]["id"])
    first.do_not_contact = True
    db.commit()
    client.post(f"/api/actions/{r['action']['id']}/approve", headers=H())
    assert db.query(Outbox).filter_by(to_name=first.name).count() == 0


def test_llm_item_placeholder_is_filled_or_neutral(client, monkeypatch):
    from app.agent import llm
    monkeypatch.setattr(llm, "write_copy", lambda *a, **k: "Namaste {name} ji! Your {item} awaits, 12% off for 7 days. 🙏")
    r = client.post("/api/retention/offers", json={"segment": "lapsed"}, headers=H()).json()
    assert r["campaign"]["copy_source"] == "llm"
    assert all("{item}" not in x["message"] and "{name}" not in x["message"] for x in r["action"]["payload"]["recipients"])


def test_chat_segments_offline(client):
    r = client.post("/api/chat", json={"message": "new vs repeat customers kitne hain"}, headers=H()).json()
    assert "known customers" in r["reply"] or "get_customer_segments" in str(r["tools"])


# ---------------------------------------------------------------- phase 3: finance
def test_finance_report_numbers_add_up(client, db):
    r = client.get("/api/finance/report?period=last_30_days", headers=H()).json()
    from app.services import analytics
    s = analytics.sales_summary(db, M(db), "last_30_days")
    assert r["collections"] == pytest.approx(s["total"], abs=0.01) and r["refunds"]["count"] == s["refund_count"]
    assert r["failed"]["count"] == s["failed_count"] and sum(r["by_mode"].values()) == pytest.approx(r["collections"], abs=0.05)
    assert r["highlights"] and r["settlements"]["total_deductions"] >= 0


def test_finance_report_partial_month_and_empty(client):
    assert client.get("/api/finance/report", headers=H()).json()["partial"] is True
    from tests.test_auth import onboard_body, signup
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    assert client.get("/api/finance/report", headers=h).json()["no_data"] is True
    assert client.get("/api/finance/forecast", headers=h).json()["no_data"] is True


def test_forecast_range_is_ordered_and_flags_cash_crunch(client):
    f1 = client.get("/api/finance/forecast", headers=H(1)).json()
    c = f1["collections"]
    assert 0 <= c["low"] <= c["likely"] <= c["high"] and f1["horizon_days"] == 30 and f1["notes"]
    f2 = client.get("/api/finance/forecast", headers=H(2)).json()  # Sharma Sweets has big bills early
    assert f2["crunch"] and f2["crunch"]["shortfall"] > 0 and f2["working_capital_needed"] > 0
    assert f1["crunch"] is None and f1["working_capital_needed"] == 0


def test_forecast_never_counts_paid_bills_or_future_noise(client, db):
    from app.models import Payable
    for p in db.query(Payable).filter_by(merchant_id=2):
        p.paid = True
    db.commit()
    f = client.get("/api/finance/forecast", headers=H(2)).json()
    assert f["bills_total"] == 0 and f["crunch"] is None


def test_finance_respects_consent_and_chat(client):
    r = client.post("/api/chat", json={"message": "next month cash flow kaisa rahega"}, headers=H()).json()
    assert "30 days" in r["reply"] or "30 din" in r["reply"]
    r = client.post("/api/chat", json={"message": "refunds kitne hue is mahine"}, headers=H()).json()
    assert "Refunds" in r["reply"] or "Collections" in r["reply"]
    client.put("/api/consent/transactions", json={"granted": False}, headers=H())
    assert client.get("/api/finance/forecast", headers=H()).status_code == 403
    assert client.get("/api/finance/report", headers=H()).status_code == 403
