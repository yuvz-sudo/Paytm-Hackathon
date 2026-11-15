"""Growth Advisor: turns the merchant's own numbers into ranked, explainable opportunities, plus week/month comparisons.
Pure functions over payments. Every figure is computed here; the LLM only phrases it."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import clock
from ..models import Merchant, Transaction
from ..util import hour_label, inr, pct_change
from . import analytics, consent, customers, inventory, ledger, settlements

BANDS = [("morning", 6, 12), ("afternoon", 12, 17), ("evening", 17, 23)]
MIN_DAYS_OF_DATA = 14


def _sum(db: Session, mid: int, start: datetime, end: datetime) -> tuple[float, int]:
    rows = db.query(Transaction.amount).filter(Transaction.merchant_id == mid, Transaction.status == "success",
                                               Transaction.ts >= start, Transaction.ts < end).all()
    return round(sum(a for (a,) in rows), 2), len(rows)


def compare(db: Session, m: Merchant) -> dict:
    """Last 7 complete days vs the 7 before; month-to-date vs the same days last month. Today (in progress) is excluded."""
    t0 = datetime.combine(clock.today(), datetime.min.time())
    out: dict = {"no_data": False}
    w_cur, wn = _sum(db, m.id, t0 - timedelta(days=7), t0)
    w_prev, wpn = _sum(db, m.id, t0 - timedelta(days=14), t0 - timedelta(days=7))
    out["week"] = {"label": "Last 7 days vs the 7 before", "current": w_cur, "previous": w_prev, "change_pct": pct_change(w_cur, w_prev),
                   "payments": wn, "previous_payments": wpn}
    day = t0.day - 1  # complete days so far this month
    if day >= 1:
        m_start = t0.replace(day=1)
        last_end = m_start
        last_start = (m_start - timedelta(days=1)).replace(day=1)
        span = min(day, (last_end - last_start).days)
        mc, mn = _sum(db, m.id, m_start, t0)
        mp, mpn = _sum(db, m.id, last_start, last_start + timedelta(days=span))
        out["month"] = {"label": f"First {day} day(s) of this month vs the same days last month", "current": mc, "previous": mp,
                        "change_pct": pct_change(mc, mp), "payments": mn, "previous_payments": mpn}
    else:
        out["month"] = None  # first of the month: nothing complete to compare yet
    out["no_data"] = w_cur == 0 and w_prev == 0
    return out


def _bands(prof: dict) -> list[dict]:
    hrs = {h["hour"]: h["avg_revenue"] for h in prof.get("hours", [])}
    out = []
    for name, a, b in BANDS:
        vals = [hrs[h] for h in range(a, b) if h in hrs]
        if vals:
            out.append({"band": name, "start": a, "end": b, "avg_hourly": round(sum(vals) / len(vals), 2), "open_hours": len(vals)})
    return out


def advisor(db: Session, m: Merchant) -> dict:
    """Ranked opportunities and the single biggest problem, each with the numbers behind it."""
    today = clock.today()
    first = db.query(Transaction.ts).filter_by(merchant_id=m.id).order_by(Transaction.ts).first()
    if not first or (today - first[0].date()).days < MIN_DAYS_OF_DATA:
        return {"no_data": True, "reason": "Need at least two weeks of payments to find reliable patterns.", "opportunities": [], "problems": [],
                "biggest_problem": None}
    opps: list[dict] = []
    prof = analytics.hourly_profile(db, m)
    wk = analytics.weekday_profile(db, m)
    s30 = analytics.sales_summary(db, m, "last_30_days")

    # 1. time-of-day gap
    bands = _bands(prof)
    if len(bands) >= 2:
        hi, lo = max(bands, key=lambda b: b["avg_hourly"]), min(bands, key=lambda b: b["avg_hourly"])
        if hi["avg_hourly"] > 0 and lo["avg_hourly"] < 0.75 * hi["avg_hourly"]:
            gap = round((hi["avg_hourly"] / lo["avg_hourly"] - 1) * 100) if lo["avg_hourly"] else None
            lift = round((hi["avg_hourly"] - lo["avg_hourly"]) * 0.2 * lo["open_hours"] * 30)  # fill 20% of the gap, 30 days
            opps.append({"id": "time_of_day", "kind": "promotion", "title": f"Try a targeted {lo['band']} offer",
                         "detail": f"Your {hi['band']} sales are {gap}% higher per hour than {lo['band']} ({hour_label(lo['start'])} to {hour_label(lo['end'])})."
                                   if gap else f"{lo['band'].title()} hours are your slowest.",
                         "est_monthly_impact": max(lift, 0), "action": "winback", "data": {"slow": lo, "busy": hi}})

    # 2. weak weekdays
    if wk and any(d["avg_revenue"] for d in wk):
        avg = sum(d["avg_revenue"] for d in wk) / len(wk)
        weak = [d for d in wk if avg and d["avg_revenue"] < 0.8 * avg]
        if weak:
            w = min(weak, key=lambda d: d["avg_revenue"])
            opps.append({"id": "weak_day", "kind": "promotion", "title": f"{w['day']} is your weakest day",
                         "detail": f"{w['day']} averages {inr(w['avg_revenue'])}, {round((1 - w['avg_revenue'] / avg) * 100)}% below your typical day ({inr(avg)}). "
                                   "A small weekday offer or festival-style combo can lift it.",
                         "est_monthly_impact": round((avg - w["avg_revenue"]) * 0.25 * 4), "action": "campaign", "data": {"weak_days": weak}})

    # 3. average order value
    if s30["payments"] >= 30:
        avg_t = s30["avg_ticket"]
        opps.append({"id": "basket", "kind": "basket", "title": "Raise your average bill",
                     "detail": f"Your average bill is {inr(avg_t)} over {s30['payments']} payments. Bundling or a 'add one more item' nudge that lifts bills by 5% "
                               "would add about " + inr(avg_t * 0.05 * s30["payments"]) + " a month.",
                     "est_monthly_impact": round(avg_t * 0.05 * s30["payments"]), "action": "campaign", "data": {"avg_ticket": avg_t}})

    # problems ranked by rupees at stake
    problems: list[dict] = []
    if consent.is_granted(db, m.id, "transactions"):
        st = inventory.stock_status(db, m, only_risky=True)
        risky = [r for r in st["items"] if r["status"] in ("out", "critical")]
        if risky:
            per_day = sum(r.get("daily_revenue") or 0 for r in risky)
            at = round(per_day * 3) if per_day else None
            problems.append({"id": "stockouts", "title": f"{len(risky)} item(s) out or about to run out", "detail": ", ".join(r["item"] for r in risky[:3]),
                             "at_stake": at, "go": "stock"})
        if s30["failed_count"]:
            problems.append({"id": "failed_payments", "title": f"{s30['failed_count']} failed payments in 30 days", "detail": f"{s30['failure_rate_pct']}% of attempts failed. Check QR and network.",
                             "at_stake": round(s30["failed_count"] * (s30["avg_ticket"] or 0) * 0.5), "go": "home"})
        stl = settlements.status(db, m)
        if stl["stuck_amount"]:
            problems.append({"id": "stuck_settlements", "title": "Settlement money not in your bank", "detail": f"{inr(stl['stuck_amount'])} is delayed or failed.",
                             "at_stake": stl["stuck_amount"], "go": "money"})
        cbs = settlements.chargebacks(db, m)
        if cbs["open_amount"]:
            problems.append({"id": "chargebacks", "title": "Open chargeback(s)", "detail": f"{inr(cbs['open_amount'])} will be debited unless proof is sent in time.",
                             "at_stake": cbs["open_amount"], "go": "money"})
    if consent.is_granted(db, m.id, "customers"):
        cu = customers.summary(db, m)
        if cu["lapsed"]:
            problems.append({"id": "lapsed", "title": f"{len(cu['lapsed'])} regular customers stopped coming", "detail": f"They spent {inr(cu['at_risk_revenue'])} in 6 months.",
                             "at_stake": round(cu["at_risk_revenue"] / 6), "go": "customers"})
    if consent.is_granted(db, m.id, "ledger"):
        d = ledger.dues(db, m)
        if d["total_overdue"]:
            problems.append({"id": "udhaar", "title": "Overdue udhaar", "detail": f"{inr(d['total_overdue'])} is past due.", "at_stake": d["total_overdue"], "go": "udhaar"})
    problems.sort(key=lambda p: p["at_stake"] or 0, reverse=True)
    opps.sort(key=lambda o: o["est_monthly_impact"], reverse=True)
    return {"no_data": False, "opportunities": opps, "problems": problems, "biggest_problem": problems[0] if problems else None,
            "note": "Impacts are rough estimates from your last 30-90 days, not promises."}
