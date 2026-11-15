from datetime import timedelta

from app import clock
from app.models import Customer, LedgerEntry, Merchant, Outbox
from app.services import actions, analytics, consent, credit, customers, gst, inventory, ledger
from tests.conftest import H


def M(db, i=1):
    return db.get(Merchant, i)


# ---------------------------------------------------------------- approval workflow
def test_nothing_is_sent_until_approved(client, db):
    r = client.post("/api/stock/order", json={}, headers=H()).json()
    assert r["proposals"] and db.query(Outbox).count() == 0
    aid = r["proposals"][0]["id"]
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).status_code == 200
    assert db.query(Outbox).count() == 1


def test_double_approve_is_idempotent(client, db):
    aid = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"][0]["id"]
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).status_code == 200
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).status_code == 409
    assert db.query(Outbox).count() == 1


def test_cannot_approve_other_merchants_action(client):
    aid = client.post("/api/stock/order", json={}, headers=H(1)).json()["proposals"][0]["id"]
    assert client.post(f"/api/actions/{aid}/approve", headers=H(2)).status_code == 404


def test_identical_proposals_are_deduplicated(client):
    a = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"]
    b = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"]
    assert {x["id"] for x in a} == {x["id"] for x in b}


def test_reject_then_approve_fails(client):
    aid = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"][0]["id"]
    assert client.post(f"/api/actions/{aid}/reject", headers=H()).status_code == 200
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).status_code == 409


def test_pending_actions_expire(client, db, monkeypatch):
    aid = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"][0]["id"]
    monkeypatch.setenv("FAKE_NOW", "2026-11-20T09:30:00")
    assert client.post(f"/api/actions/{aid}/approve", headers=H()).status_code == 409


def test_reminder_not_sent_if_customer_already_paid(client, db):
    dues = client.get("/api/udhaar", headers=H()).json()["customers"]
    c = dues[0]
    aid = client.post("/api/udhaar/remind", json={"customer": c["name"]}, headers=H()).json()["proposals"][0]["id"]
    client.post("/api/udhaar/payment", json={"customer": c["name"], "amount": c["outstanding"]}, headers=H())
    resp = client.post(f"/api/actions/{aid}/approve", headers=H())
    r = resp.json()
    assert resp.status_code == 200, r
    assert r["status"] == "failed" and db.query(Outbox).filter_by(to_name=c["name"]).count() == 0


def test_messaging_consent_blocks_send(client, db):
    aid = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"][0]["id"]
    client.put("/api/consent/messaging", json={"granted": False}, headers=H())
    r = client.post(f"/api/actions/{aid}/approve", headers=H()).json()
    assert r["status"] == "failed" and db.query(Outbox).count() == 0


def test_edited_message_is_what_gets_sent(client, db):
    aid = client.post("/api/stock/order", json={}, headers=H()).json()["proposals"][0]["id"]
    client.post(f"/api/actions/{aid}/approve", json={"edited_message": "Custom order text"}, headers=H())
    assert db.query(Outbox).first().body == "Custom order text"


# ---------------------------------------------------------------- consent
def test_consent_off_blocks_api_and_chat(client):
    client.put("/api/consent/ledger", json={"granted": False}, headers=H())
    assert client.get("/api/udhaar", headers=H()).status_code == 403
    r = client.post("/api/chat", json={"message": "udhaar kitna baaki hai"}, headers=H()).json()
    assert "permission band" in r["reply"] and "₹" not in r["reply"]


def test_briefing_respects_consent_and_recomputes(client):
    first = client.get("/api/briefing", headers=H()).json()
    assert first["sales"] is not None
    client.put("/api/consent/transactions", json={"granted": False}, headers=H())
    second = client.get("/api/briefing", headers=H()).json()
    assert second["sales"] is None and "transactions" in second["blocked_scopes"]


# ---------------------------------------------------------------- analytics
def test_totals_exclude_failed_and_refunded(db):
    s = analytics.sales_summary(db, M(db), "yesterday")
    assert s["total"] > 0 and s["failed_count"] >= 0
    from app.models import Transaction
    start, end, _ = __import__("app.util", fromlist=["x"]).resolve_period("yesterday")
    all_ok = sum(t.amount for t in db.query(Transaction).filter(Transaction.merchant_id == 1, Transaction.ts >= start, Transaction.ts < end, Transaction.status == "success"))
    assert abs(all_ok - s["total"]) < 0.01


def test_no_future_payments_today(db):
    s = analytics.sales_summary(db, M(db), "today")
    assert s["end"] <= clock.now().isoformat()


def test_best_sellers_reports_coverage(db):
    b = analytics.best_sellers(db, M(db), "last_7_days")
    assert 50 <= b["coverage_pct"] <= 100 and b["items"]


def test_empty_period_is_not_an_error(db):
    s = analytics.sales_summary(db, M(db), "2020-01-01")
    assert s["no_data"] and s["total"] == 0 and s["change_pct"] is None


# ---------------------------------------------------------------- inventory
def test_stock_flags_expected_items(db):
    st = inventory.stock_status(db, M(db))
    by = {r["item"]: r for r in st["items"]}
    assert by["Atta 5kg"]["status"] in ("critical", "low", "out")
    assert by["Turmeric Powder"]["status"] == "unknown"  # never reported: do not guess


def test_salon_has_no_stock(db):
    assert inventory.stock_status(db, M(db, 3))["tracks_stock"] is False


def test_update_stock_validation(db):
    m = M(db)
    assert inventory.update_stock(db, m, "atta", -5)["error"] == "invalid_quantity"
    assert inventory.update_stock(db, m, "unicorn food", 5)["error"] == "item_not_found"
    assert inventory.update_stock(db, m, "chai", 5)["error"] == "item_not_stock_tracked"
    ok = inventory.update_stock(db, m, "आटा", 300)
    assert ok["ok"] and ok["item"] == "Atta 5kg"  # Hindi alias resolves
    row = next(r for r in inventory.stock_status(db, m)["items"] if r["item"] == "Atta 5kg")
    assert row["status"] == "ok"


def test_perishables_are_not_overordered(client):
    r = client.post("/api/stock/order", json={"items": ["milk"]}, headers=H()).json()
    qty = r["proposals"][0]["payload"]["lines"][0]["qty"]
    st = client.get("/api/stock", headers=H()).json()
    pace = next(i for i in st["items"] if i["item"] == "Amul Milk 500ml")["daily_pace"]
    assert qty <= pace * 5 + 24  # ~2 days cover + lead time, not a week+


# ---------------------------------------------------------------- ledger
def test_fifo_and_balance(db):
    m = M(db)
    c = Customer(merchant_id=m.id, name="Test Person", phone="+91 9000000000", created_at=clock.now())
    db.add(c); db.flush()
    now = clock.now()
    db.add_all([
        LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="credit_given", amount=500, ts=now - timedelta(days=40), due_date=(now - timedelta(days=25)).date()),
        LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="credit_given", amount=300, ts=now - timedelta(days=5), due_date=(now + timedelta(days=10)).date()),
        LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="payment_received", amount=500, ts=now - timedelta(days=2)),
    ])
    db.commit()
    row = next(r for r in ledger.dues(db, m)["customers"] if r["name"] == "Test Person")
    assert row["outstanding"] == 300 and row["overdue"] == 0 and row["oldest_days"] == 5  # old debt cleared first


def test_payment_validation(db):
    m = M(db)
    name = ledger.dues(db, m)["customers"][0]["name"]
    bal = ledger.dues(db, m)["customers"][0]["outstanding"]
    assert ledger.record_payment(db, m, name, 0)["error"] == "invalid_amount"
    assert ledger.record_payment(db, m, name, bal + 1000)["error"] == "exceeds_balance"
    assert ledger.record_payment(db, m, "Nonexistent Zed", 10)["error"] == "customer_not_found"
    assert ledger.add_credit(db, m, name, float("nan"))["error"] == "invalid_amount"
    assert ledger.add_credit(db, m, name, 1e12)["error"] == "invalid_amount"


def test_do_not_contact_is_respected(client, db):
    c = ledger.dues(db, M(db))["customers"][0]
    db.get(Customer, c["customer_id"]).do_not_contact = True
    db.commit()
    r = client.post("/api/udhaar/remind", json={"customer": c["name"]}, headers=H()).json()
    assert r["proposals"] == [] and r["skipped"][0]["reason"] == "opted_out"


# ---------------------------------------------------------------- customers / offers
def test_winback_discount_is_capped(client):
    r = client.post("/api/customers/winback", json={"discount_pct": 60}, headers=H()).json()
    assert r["discount_pct"] == 15 and r["discount_capped"]


# ---------------------------------------------------------------- gst / credit
def test_gst_unregistered_and_unallocated(db):
    assert gst.summary(db, M(db, 3), "last_month")["registered"] is False
    g = gst.summary(db, M(db), "last_month")
    assert g["registered"] and g["unallocated_sales"] > 0 and g["estimated_tax"] > 0


def test_credit_only_suggested_when_gap_exists(db):
    assert credit.suggestion(db, M(db, 1))["needs_credit"] is False
    s = credit.suggestion(db, M(db, 2))
    assert s["needs_credit"] and s["suggested_amount"] > 0 and "disclaimer" in s


# ---------------------------------------------------------------- chat / agent
def test_confirmation_flow_and_guard(client, db):
    r = client.post("/api/chat", json={"message": "order kar do supplier ko"}, headers=H()).json()
    sid = r["session_id"]
    assert r["pending_actions"] and db.query(Outbox).count() == 0
    # an unrelated question moves on: a later stray "haan" must NOT approve the stale proposal
    client.post("/api/chat", json={"message": "kitni sales hui", "session_id": sid}, headers=H())
    client.post("/api/chat", json={"message": "haan bhej do", "session_id": sid}, headers=H())
    assert db.query(Outbox).count() == 0
    # the direct flow works: propose -> yes
    r = client.post("/api/chat", json={"message": "order kar do supplier ko", "session_id": sid}, headers=H()).json()
    r2 = client.post("/api/chat", json={"message": "haan bhej do", "session_id": sid}, headers=H()).json()
    assert db.query(Outbox).count() == len(r["pending_actions"]) > 0 and "Approve ho gaya" in r2["reply"]
    # and the same "yes" again does nothing
    client.post("/api/chat", json={"message": "haan", "session_id": sid}, headers=H())
    assert db.query(Outbox).count() == len(r["pending_actions"])


def test_yes_without_pending_does_nothing(client, db):
    client.post("/api/chat", json={"message": "haan bhej do"}, headers=H())
    assert db.query(Outbox).count() == 0


def test_voice_style_commands(client):
    def say(msg):
        return client.post("/api/chat", json={"message": msg}, headers=H()).json()["reply"]
    assert "likh liya" in say("Mohan Singh ka 500 udhaar likho") or "Noted" in say("Mohan Singh ka 500 udhaar likho")
    assert "Update" in say("atta 20 bag aaya") or "अपडेट" in say("atta 20 bag aaya")
    assert "kal" in say("कल की बिक्री").lower() or "कल" in say("कल की बिक्री")


def test_garbage_input_is_safe(client):
    for msg in ["", "   ", "asdkjh qwe", "💥" * 50, "'; DROP TABLE merchants; --", "x" * 5000]:
        r = client.post("/api/chat", json={"message": msg[:2000]}, headers=H())
        assert r.status_code == 200 and r.json()["reply"]


def test_hindi_script_gets_hindi_reply(client):
    r = client.post("/api/chat", json={"message": "आज की बिक्री कितनी हुई"}, headers=H()).json()
    assert r["language"] == "hi" and "बिक्री" in r["reply"]


def test_unknown_merchant_and_bad_header(client):
    assert client.get("/api/briefing", headers=H(999)).status_code == 404
    assert client.get("/api/briefing", headers={"X-Merchant-Id": "abc"}).status_code == 422


def test_series_excludes_partial_today(db):
    series = analytics.daily_series(db, M(db), 30)
    assert series[-1]["date"] == (clock.today() - timedelta(days=1)).isoformat() and len(series) == 30


def test_briefing_refreshes_after_changes(client):
    before = client.get("/api/briefing", headers=H()).json()
    top = client.get("/api/udhaar", headers=H()).json()["customers"][0]
    client.post("/api/udhaar/payment", json={"customer": top["name"], "amount": top["outstanding"]}, headers=H())
    after = client.get("/api/briefing", headers=H()).json()
    pick = lambda b: next(c for c in b["cards"] if c["id"] == "udhaar")["detail"]  # noqa: E731
    assert pick(before) != pick(after)


# ---------------------------------------------------------------- richer assistant
def _say(client, msg, sid=None, mid=1):
    r = client.post("/api/chat", json={"message": msg, "session_id": sid}, headers=H(mid)).json()
    return r


def test_item_specific_questions(client):
    r = _say(client, "atta kitna bacha hai")
    assert r["intent"] == "item_info" and "Atta 5kg" in r["reply"] and "days left" in r["reply"] + "days left" and "bika" in r["reply"]
    assert "Atta 5kg" in _say(client, "how much sugar left")["reply"] or "Sugar" in _say(client, "how much sugar left")["reply"]


def test_explain_why_sales_dropped(client):
    r = _say(client, "kal sales kam kyu hui", mid=2)
    assert r["intent"] == "explain" and "₹13,040" in r["reply"] and "Diwali" in r["reply"]


def test_follow_up_remembers_topic(client):
    a = _say(client, "kal ki sales")
    b = _say(client, "aur is hafte?", a["session_id"])
    assert b["intent"] == "sales" and "7 din" in b["reply"]


def test_multi_part_question(client):
    r = _say(client, "sales aur stock batao")
    assert "sales" in r["reply"].lower() and "stock" in r["reply"].lower() and "\n" in r["reply"]


def test_spoken_number_words_for_amounts(client):
    r = _say(client, "Mohan Singh ka paanch sau udhaar likho")
    assert "₹500" in r["reply"]


def test_customer_balance_and_advice(client):
    name = client.get("/api/udhaar", headers=H()).json()["customers"][0]["name"]
    assert "baaki" in _say(client, f"{name} ka kitna baaki hai")["reply"]
    assert _say(client, "aaj kya karna chahiye")["intent"] == "advice"


def test_llm_path_falls_back_to_rules_on_failure(client, monkeypatch):
    from app.agent import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
    r = _say(client, "kal ki sales kitni thi")
    assert r["engine"] == "rules" and "₹" in r["reply"]


def test_llm_never_decides_confirmations(client, db, monkeypatch):
    from app.agent import llm
    called = []
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: called.append(1) or "x")
    r = _say(client, "order kar do supplier ko")  # goes to llm stub (returns "x"), no proposals
    assert called and db.query(Outbox).count() == 0
    r2 = _say(client, "haan bhej do", r["session_id"])  # no pending => must not approve or call the LLM for it
    assert db.query(Outbox).count() == 0


def test_todays_transactions_only_today_and_totals_exclude_failed(client):
    r = client.get("/api/transactions/today", headers={"X-Merchant-Id": "1"})
    assert r.status_code == 200
    d = r.json()
    assert d["date"] == "2026-11-14"
    assert all(t["ts"].startswith("2026-11-14") for t in d["transactions"])
    assert d["total"] == round(sum(t["amount"] for t in d["transactions"] if t["status"] == "success"), 2)
    assert d["count"] == sum(t["status"] == "success" for t in d["transactions"])
    ts = [t["ts"] for t in d["transactions"]]
    assert ts == sorted(ts, reverse=True)


def test_yesterdays_transactions_match_yesterdays_sales(client):
    h = {"X-Merchant-Id": "1"}
    d = client.get("/api/transactions?day=yesterday", headers=h).json()
    s = client.get("/api/sales/summary?period=yesterday", headers=h).json()
    assert d["date"] == "2026-11-13" and d["complete"] is True
    assert all(t["ts"].startswith("2026-11-13") for t in d["transactions"])
    assert d["total"] == s["total"] and d["count"] == s["payments"]
    assert d["refund_count"] == s["refund_count"] and d["failed_count"] == s["failed_count"]
    assert client.get("/api/transactions?day=lastyear", headers=h).status_code == 422


def test_reviews_section_is_gone(client):
    h = {"X-Merchant-Id": "1"}
    assert client.get("/api/reviews", headers=h).status_code == 404
    assert "reviews" not in {c["scope"] if isinstance(c, dict) else c for c in client.get("/api/consent", headers=h).json()}
    b = client.get("/api/briefing", headers=h).json()
    assert not any(c["id"] == "reviews" for c in b["cards"]) and "review" not in b["script"].lower()
    r = client.post("/api/chat", headers=h, json={"message": "any reviews to reply to?", "language": "en"})
    assert r.status_code == 200 and r.json()["reply"]
