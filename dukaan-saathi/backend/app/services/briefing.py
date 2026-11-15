"""Daily briefing: structured data (for the dashboard) plus a short spoken script (for the Soundbox).
Computed per merchant in a nightly batch and cached; each section honours consent."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from .. import clock, i18n
from ..languages import NATIVE
from ..models import Briefing, Merchant
from ..util import inr, qty_fmt
from . import sarvam
from . import analytics, calendar, consent, credit, customers, gst, inventory, ledger, settlements

log = logging.getLogger("dukaan.briefing")


def _safe(db, m, scope, fn, default=None):
    if not consent.is_granted(db, m.id, scope):
        return default, True
    return fn(), False


def _driver_text(x: dict) -> str:
    """One plain sentence for why a day differed: footfall vs bill size, biggest hour and item swing."""
    if x["driver"] == "footfall":
        out = f"{'fewer' if (x['payments_change_pct'] or 0) < 0 else 'more'} customers ({x['payments']} payments vs {x['ref_payments']})"
    else:
        out = f"{'smaller' if (x['ticket_change_pct'] or 0) < 0 else 'bigger'} bills (average {inr(x['avg_ticket'])} vs {inr(x['ref_avg_ticket'])})"
    if x.get("item_swings"):
        i = x["item_swings"][0]
        out += f"; biggest item change: {i['item']} ({'+' if i['delta'] > 0 else '-'}{inr(abs(i['delta']))})"
    return out


def _gst_detail(g: dict) -> str:
    def part(name: str, days: int) -> str:
        return f"{name} due in {days} days" if days > 0 else f"{name} due today" if days == 0 else f"{name} was due {-days} days ago (confirm it is filed)"
    return f"{part('GSTR-1', g['days_to_gstr1'])}; {part('GSTR-3B', g['days_to_gstr3b'])}"


def _hi_detail(c: dict) -> str | None:
    """Hindi text for alert cards (numbers and names come from the card data)."""
    d, cid = c.get("data"), c["id"]
    try:
        if cid == "settle_fail":
            return f"{inr(d['amount'])} आपके बैंक तक नहीं पहुँचे: {d['failure_reason']}"
        if cid == "settle_delay":
            return f"{inr(d['amount'])}, जो {d['expected_date']} तक आने थे, अभी नहीं आए"
        if cid == "chargeback":
            return (f"{inr(d['amount'])} के सबूत की तारीख {-d['days_left']} दिन पहले निकल चुकी है" if d["days_left"] < 0
                    else f"{d['days_left']} दिन में सबूत न भेजा तो {inr(d['amount'])} कट जाएगा")
        if cid == "stock":
            return ", ".join(f"{r['item']} (~{r['days_left']:.0f} दिन)" if r.get("days_left") is not None else f"{r['item']} (खत्म)" for r in d)
        if cid == "sales_drop":
            return f"सामान्य {i18n.weekday('hi', d['weekday'])} से {abs(d['change_pct']):.0f}% कम ({inr(d['yesterday'])} बनाम {inr(d['typical'])})"
        if cid == "pay_fail":
            return f"{d['count']} भुगतान विफल हुए ({d['pct']}%)। नेटवर्क/QR जाँचें।"
        if cid == "refund":
            return f"कल {d['count']} रिफंड ({d['pct']}%)"
        if cid == "cash_gap":
            return f"{d['horizon_days']} दिनों में {inr(d['bills_due_total'])} के बिल देय हैं; अनुमानित बिक्री {inr(d['expected_inflow'])} कवर करेगी"
        if cid == "udhaar":
            return c["detail"].replace("customers owe", "ग्राहकों पर बाकी").replace("overdue", "तारीख निकल चुकी")
        if cid == "lapsed":
            return f"{d['count']} नियमित ग्राहक, पिछले 6 महीने में {inr(d['amount'])} का खर्च"
        if cid == "gst":
            a, b = d["days_to_gstr1"], d["days_to_gstr3b"]
            f = lambda n, x: f"{n} {x} दिन में" if x > 0 else f"{n} आज" if x == 0 else f"{n} {-x} दिन पहले था (फाइल हुआ या नहीं जाँचें)"  # noqa: E731
            return f"{f('GSTR-1', a)}; {f('GSTR-3B', b)}"
        if cid == "gst_threshold":
            return f"अनुमानित वार्षिक टर्नओवर {inr(d['annualised_turnover'])}, सीमा {inr(d['registration_threshold'])}"
        if cid == "festival":
            return f"{d['days']} दिन में। {d.get('hint_hi') or d['hint']}"
    except Exception:
        return None
    return None


def _empty(db: Session, m: Merchant) -> dict:
    """First-run state: no payments yet. Show a welcome and a setup checklist instead of blank cards."""
    from ..models import Item, Supplier
    lang = m.language
    has_items = db.query(Item.id).filter_by(merchant_id=m.id, active=True).first() is not None
    has_sup = db.query(Supplier.id).filter_by(merchant_id=m.id).first() is not None
    cards = []
    if not has_items:
        cards.append({"id": "setup_items", "severity": "info", "icon": "box", "title": "Add your items",
                      "detail": "List what you sell with prices so Saathi can track stock and best sellers.", "data": None})
    if not has_sup:
        cards.append({"id": "setup_suppliers", "severity": "info", "icon": "users", "title": "Add your suppliers",
                      "detail": "With a supplier's number Saathi can draft re-orders for your approval.", "data": None})
    cards.append({"id": "setup_sample", "severity": "info", "icon": "star", "title": "Explore with sample data",
                  "detail": "See how Dukaan Saathi looks with a month of simulated payments. You can remove it any time.", "data": None})
    script = i18n.t(lang, "welcome_empty", name=m.owner_name.split()[0] if m.owner_name else "")
    return {"date": clock.today().isoformat(), "merchant": {"id": m.id, "name": m.name, "owner": m.owner_name, "language": lang},
            "sales": None, "best_sellers": None, "cards": cards, "script": script, "script_lines": [script], "blocked_scopes": [], "empty": True}


def build(db: Session, m: Merchant) -> dict:
    lang = m.language
    from ..models import Transaction
    if db.query(Transaction.id).filter_by(merchant_id=m.id).first() is None:
        return _empty(db, m)
    blocked: list[str] = []

    def sect(scope, fn):
        v, off = _safe(db, m, scope, fn)
        if off:
            blocked.append(scope)
        return v

    sales = sect("transactions", lambda: analytics.sales_summary(db, m, "yesterday"))
    best = sect("transactions", lambda: analytics.best_sellers(db, m, "yesterday", 3))
    stock = sect("transactions", lambda: inventory.stock_status(db, m, only_risky=True))
    anomalies = sect("transactions", lambda: analytics.anomalies(db, m))
    settle = sect("transactions", lambda: settlements.status(db, m))
    gst_s = sect("transactions", lambda: gst.summary(db, m, "last_month")) if m.gst_registered else None
    dues = sect("ledger", lambda: ledger.dues(db, m))
    cust = sect("customers", lambda: customers.summary(db, m))
    cash = sect("credit", lambda: credit.cashflow(db, m))
    fest = calendar.upcoming(m.segment, 14)
    past = calendar.recent(m.segment, 7)

    cards: list[dict] = []  # severity: high | medium | info ; ordered later
    spoken_alerts: list[str] = []

    if settle:
        for s in settle["failed"][:1]:
            cards.append({"id": "settle_fail", "severity": "high", "icon": "bank", "title": "Settlement failed",
                          "detail": f"{inr(s['amount'])} could not reach your bank: {s['failure_reason']}", "data": s})
            spoken_alerts.append(i18n.t(lang, "settle_fail", amt=inr(s["amount"]), reason=s["failure_reason"]))
        for s in settle["delayed"][:1]:
            cards.append({"id": "settle_delay", "severity": "high", "icon": "bank", "title": "Settlement delayed",
                          "detail": f"{inr(s['amount'])} expected on {s['expected_date']} has not arrived", "data": s})
            spoken_alerts.append(i18n.t(lang, "settle_delay", amt=inr(s["amount"]), days=s["days_late"]))
    if settle:
        cbs = [c for c in settlements.chargebacks(db, m)["chargebacks"] if c["status"] == "open"]
        for c in cbs[:1]:
            late = c["days_left"] < 0
            cards.append({"id": "chargeback", "severity": "high" if c["urgent"] else "medium", "icon": "alert",
                          "title": "Chargeback: send proof",
                          "detail": (f"Deadline for {inr(c['amount'])} passed {-c['days_left']} day(s) ago" if late
                                     else f"{inr(c['amount'])} will be debited unless you send proof in {c['days_left']} day(s)"), "data": c})
            spoken_alerts.insert(0, i18n.t(lang, "chargeback_late" if late else "chargeback_due", amt=inr(c["amount"]), days=max(c["days_left"], 0)))
    if stock and stock["items"]:
        risky = [r for r in stock["items"] if r["status"] in ("out", "critical", "low")]
        if risky:
            top = risky[:3]
            names = ", ".join(r["item"] for r in top)
            cards.append({"id": "stock", "severity": "high" if top[0]["status"] in ("out", "critical") else "medium", "icon": "box",
                          "title": "Stock running low", "detail": ", ".join(
                              f"{r['item']} (~{r['days_left']:.0f}d)" if r.get("days_left") is not None else r["item"] for r in top),
                          "data": top})
            outs = [r for r in top if r["status"] == "out"]
            if outs:
                spoken_alerts.append(i18n.t(lang, "stock_out", items=", ".join(r["item"] for r in outs)))
            soon = [r for r in top if r["status"] != "out" and r.get("days_left") is not None]
            if soon:
                spoken_alerts.append(i18n.t(lang, "stock_soon", items=", ".join(r["item"] for r in soon[:2]),
                                            days=max(1, round(min(r["days_left"] for r in soon[:2])))) + " " + i18n.t(lang, "offer_order"))
    for a in anomalies or []:
        if a["type"] == "sales_drop":
            try:
                a["why"] = analytics.explain_change(db, m)
            except Exception:  # the card must still show without a reason
                a["why"] = None
            cards.append({"id": "sales_drop", "severity": a["severity"], "icon": "trend-down", "title": "Sales dip",
                          "detail": f"{abs(a['change_pct']):.0f}% below a typical {a['weekday']} ({inr(a['yesterday'])} vs {inr(a['typical'])})"
                                    + (f". This follows {past[0]['name']}, so a dip is expected." if past else "")
                                    + (f". Mainly {_driver_text(a['why'])}." if a.get("why") and not a["why"].get("no_data") else ""), "data": a})
            if not past:  # a post-festival dip is normal; don't alarm the merchant by voice
                spoken_alerts.append(i18n.t(lang, "sales_drop", pct=round(abs(a["change_pct"])), weekday=i18n.weekday(lang, a["weekday"])))
        elif a["type"] == "payment_failures":
            cards.append({"id": "pay_fail", "severity": "medium", "icon": "alert", "title": "Many failed payments",
                          "detail": f"{a['count']} payments failed ({a['pct']}%). Check your network/QR.", "data": a})
        elif a["type"] == "refund_spike":
            cards.append({"id": "refund", "severity": "medium", "icon": "alert", "title": "Refunds higher than usual",
                          "detail": f"{a['count']} refunds yesterday ({a['pct']}%)", "data": a})
    if cash and cash["has_gap"]:
        cards.append({"id": "cash_gap", "severity": "high", "icon": "wallet", "title": "Cash-flow gap ahead",
                      "detail": f"{inr(cash['bills_due_total'])} of bills due in {cash['horizon_days']} days; expected sales cover {inr(cash['expected_inflow'])}",
                      "data": cash})
        spoken_alerts.append(i18n.t(lang, "cash_gap", bills=inr(cash["bills_due_total"]), cover=inr(cash["expected_inflow"])))
    if dues and dues["count"]:
        cards.append({"id": "udhaar", "severity": "medium" if dues["total_overdue"] > 0 else "info", "icon": "book", "title": "Udhaar pending",
                      "detail": f"{dues['count']} customers owe {inr(dues['total_outstanding'])}" +
                                (f" ({inr(dues['total_overdue'])} overdue)" if dues["total_overdue"] else ""), "data": dues["aging"]})
        spoken_alerts.append(i18n.t(lang, "dues", n=dues["count"], total=inr(dues["total_outstanding"])))
    if cust and cust["lapsed"]:
        cards.append({"id": "lapsed", "severity": "info", "icon": "users", "title": "Regulars who stopped coming",
                      "detail": f"{len(cust['lapsed'])} regulars, {inr(cust['at_risk_revenue'])} spent in the last 6 months",
                      "data": {"count": len(cust["lapsed"]), "amount": cust["at_risk_revenue"], "top": cust["lapsed"][:3]}})
        spoken_alerts.append(i18n.t(lang, "lapsed", n=len(cust["lapsed"])))
    if gst_s and gst_s.get("days_to_gstr1") is not None and -3 <= gst_s["days_to_gstr1"] <= 5:
        cards.append({"id": "gst", "severity": "medium", "icon": "file", "title": "GST filing due soon",
                      "detail": _gst_detail(gst_s), "data": gst_s})
        if gst_s["days_to_gstr1"] >= 0:
            spoken_alerts.append(i18n.t(lang, "gst_due", days=gst_s["days_to_gstr1"]))
    if gst_s and not m.gst_registered:
        pass
    if not m.gst_registered:
        g = gst.summary(db, m, "last_month") if consent.is_granted(db, m.id, "transactions") else None
        if g and g.get("threshold_alert"):
            cards.append({"id": "gst_threshold", "severity": "medium", "icon": "file", "title": "Nearing GST registration limit",
                          "detail": f"Annualised turnover {inr(g['annualised_turnover'])} vs limit {inr(g['registration_threshold'])}", "data": g})
    for f in fest[:1]:
        cards.append({"id": "festival", "severity": "info", "icon": "calendar", "title": f["name"],
                      "detail": f"In {f['days']} days. {f['hint']}", "data": f})
        spoken_alerts.append(i18n.t(lang, "festival", name=f["name"], days=f["days"], hint=f["hint_hi"] if i18n.lang_of(lang) == "hi" else f["hint"]))

    sev = {"high": 0, "medium": 1, "info": 2}
    cards.sort(key=lambda c: sev[c["severity"]])
    if i18n.lang_of(lang) == "hi":
        for c in cards:
            c["detail"] = _hi_detail(c) or c["detail"]

    # spoken script
    hr = clock.now().hour
    greet = "greet_morning" if hr < 12 else "greet_afternoon" if hr < 17 else "greet_evening"
    lines = [i18n.t(lang, greet, name=m.owner_name.split()[0])]
    if sales is None:
        pass
    elif sales["no_data"]:
        lines.append(i18n.t(lang, "no_sales"))
    else:
        lines.append(i18n.t(lang, "sales_line", total=inr(sales["total"]), n=sales["payments"]))
        if sales["change_pct"] is not None and abs(sales["change_pct"]) >= 5:
            lines.append(i18n.t(lang, "vs_up" if sales["change_pct"] > 0 else "vs_down", pct=abs(round(sales["change_pct"]))))
        if best and best["items"]:
            lines.append(i18n.t(lang, "best", item=best["items"][0]["item"]))
    lines += spoken_alerts[:3]
    if not spoken_alerts and sales and not sales["no_data"]:
        lines.append(i18n.t(lang, "all_good"))
    if blocked:
        lines.append(f"({', '.join(sorted(set(blocked)))}: access off)")

    return {
        "date": clock.today().isoformat(), "merchant": {"id": m.id, "name": m.name, "owner": m.owner_name, "language": lang},
        "sales": sales, "best_sellers": best, "cards": cards, "script": " ".join(lines), "script_lines": lines,
        "blocked_scopes": sorted(set(blocked)), "empty": False,
    }


def get_or_create(db: Session, m: Merchant, refresh: bool = False) -> dict:
    today = clock.today()
    row = db.query(Briefing).filter_by(merchant_id=m.id, for_date=today).first()
    # re-use only if consent state did not change since (blocked scopes are part of the cached data)
    if row and not refresh:
        cached_blocked = set(row.data.get("blocked_scopes", []))
        now_blocked = {s for s in consent.SCOPES if not consent.is_granted(db, m.id, s)}
        if cached_blocked <= now_blocked and now_blocked & {"transactions", "ledger", "customers", "credit"} == cached_blocked:
            if not _needs_translation(m, row.data):
                return row.data
    data = _localise(db, m, build(db, m))
    if row:
        row.data, row.created_at = data, clock.now()
    else:
        db.add(Briefing(merchant_id=m.id, for_date=today, data=data, created_at=clock.now()))
    db.commit()
    return data


def _needs_translation(m: Merchant, data: dict) -> bool:
    """A cached English briefing for a Tamil/Bengali/... merchant is retried once translation is reachable again."""
    return m.language in NATIVE and data.get("translated_to") != m.language and sarvam.available()


def _localise(db: Session, m: Merchant, data: dict) -> dict:
    if m.language not in NATIVE:
        return data
    try:
        lines = sarvam.translate_many(db, data["script_lines"], m.language, merchant_id=m.id, templated=False)
    except Exception as e:  # translation is a nicety: keep the English briefing
        log.warning("briefing translation failed: %s", e)
        db.rollback()
        return data
    done = lines != data["script_lines"] or not data["script_lines"]
    return {**data, "script_lines": lines, "script": " ".join(lines), "translated_to": m.language if done else None}


def invalidate(db: Session, merchant_id: int) -> None:
    """Drop today's cached briefing after the merchant changes data, so it is rebuilt fresh on next view."""
    db.query(Briefing).filter_by(merchant_id=merchant_id, for_date=clock.today()).delete()
