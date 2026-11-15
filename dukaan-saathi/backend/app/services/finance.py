"""Finance assistant: a plain-language report (collections, refunds, failures, settlement deductions) and a cautious 30-day
forecast with a working-capital check. Pure functions over payments, settlements and bills; no LLM involved."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, pstdev

from sqlalchemy.orm import Session

from .. import clock
from ..models import Merchant, Payable, Settlement, SettlementLine, Supplier, Transaction
from ..util import inr, pct_change, resolve_period
from . import calendar

FORECAST_DAYS = 30
HISTORY_WEEKS = 8
MIN_HISTORY_DAYS = 28
USABLE = 0.85  # same cautious share of inflow the credit check uses (running costs are not tracked here)


def report(db: Session, m: Merchant, period: str | None = "this_month") -> dict:
    start, end, label = resolve_period(period if period else "this_month")
    span = end - start
    rows = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.ts >= start, Transaction.ts < end).all()
    if not rows:
        return {"period": label, "start": start.isoformat(), "end": end.isoformat(), "no_data": True}
    ok = [t for t in rows if t.status == "success"]
    refunds = [t for t in rows if t.status == "refunded"]
    failed = [t for t in rows if t.status == "failed"]
    coll = round(sum(t.amount for t in ok), 2)
    by_mode: dict[str, float] = defaultdict(float)
    for t in ok:
        by_mode[t.mode] += t.amount
    prev = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.ts >= start - span, Transaction.ts < start).all()
    prev_coll = round(sum(t.amount for t in prev if t.status == "success"), 2)
    prev_ref = round(sum(t.amount for t in prev if t.status == "refunded"), 2)
    ref_amt = round(sum(t.amount for t in refunds), 2)
    fail_amt = round(sum(t.amount for t in failed), 2)
    sets = db.query(Settlement).filter(Settlement.merchant_id == m.id, Settlement.expected_date >= start.date(), Settlement.expected_date < end.date()).all()
    ids = [s.id for s in sets]
    ded: dict[str, float] = defaultdict(float)
    if ids:
        for ln in db.query(SettlementLine).filter(SettlementLine.settlement_id.in_(ids)):
            ded[ln.kind] += ln.amount
    out = {
        "period": label, "start": start.isoformat(), "end": end.isoformat(), "partial": label in ("this_month", "today"), "no_data": False,
        "collections": coll, "payments": len(ok), "avg_ticket": round(coll / len(ok), 2) if ok else 0.0,
        "collections_change_pct": pct_change(coll, prev_coll), "previous_collections": prev_coll,
        "refunds": {"count": len(refunds), "amount": ref_amt, "pct_of_collections": round(ref_amt / coll * 100, 1) if coll else 0.0,
                    "change_pct": pct_change(ref_amt, prev_ref)},
        "failed": {"count": len(failed), "amount": fail_amt, "rate_pct": round(len(failed) / (len(ok) + len(failed)) * 100, 1) if (ok or failed) else 0.0},
        "by_mode": {k: round(v, 2) for k, v in sorted(by_mode.items(), key=lambda kv: -kv[1])},
        "settlements": {"settled": round(sum(s.amount for s in sets if s.status == "settled"), 2),
                        "pending": round(sum(s.amount for s in sets if s.status == "pending"), 2),
                        "failed": round(sum(s.amount for s in sets if s.status == "failed"), 2),
                        "deductions": {k: round(v, 2) for k, v in ded.items()}, "total_deductions": round(sum(ded.values()), 2)},
    }
    hl = [f"Collections {inr(coll)} from {len(ok)} payments" + (f" ({'up' if out['collections_change_pct'] >= 0 else 'down'} {abs(out['collections_change_pct'])}% vs the previous period)" if out["collections_change_pct"] is not None else "") + "."]
    if refunds:
        hl.append(f"Refunds {inr(ref_amt)} ({out['refunds']['pct_of_collections']}% of collections) across {len(refunds)} payments.")
    if failed:
        hl.append(f"{len(failed)} failed payments ({out['failed']['rate_pct']}% of attempts), about {inr(fail_amt)} that may not have been collected.")
    if out["settlements"]["failed"] or out["settlements"]["pending"]:
        hl.append(f"{inr(out['settlements']['failed'] + out['settlements']['pending'])} of settlements are still pending or failed.")
    if ded:
        hl.append(f"Paytm deductions on settlements: {inr(out['settlements']['total_deductions'])}.")
    out["highlights"] = hl
    return out


def forecast(db: Session, m: Merchant) -> dict:
    """Next 30 days: collections (low / likely / high) from the last 8 weeks by weekday, bills due, and when cash may get tight."""
    today = clock.today()
    t0 = datetime(today.year, today.month, today.day)
    first = db.query(Transaction.ts).filter_by(merchant_id=m.id).order_by(Transaction.ts).first()
    if not first or (today - first[0].date()).days < MIN_HISTORY_DAYS:
        return {"no_data": True, "reason": "not_enough_history", "need_days": MIN_HISTORY_DAYS}
    since = t0 - timedelta(weeks=HISTORY_WEEKS)
    per_day: dict = defaultdict(float)
    for t in db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.status == "success", Transaction.ts >= since, Transaction.ts < t0):
        per_day[t.ts.date()] += t.amount
    by_wd: dict[int, list[float]] = defaultdict(list)
    weekly: list[float] = []
    for w in range(HISTORY_WEEKS):
        tot = 0.0
        for i in range(7):
            d = (t0 - timedelta(days=7 * (w + 1) - i)).date()
            v = per_day.get(d, 0.0)
            by_wd[d.weekday()].append(v)
            tot += v
        weekly.append(tot)
    # cautious: the lower of the 8-week and the last-4-weeks weekday average, so a past festival spike does not inflate the forecast
    wd_avg = {k: min(mean(v), mean(v[:4])) for k, v in by_wd.items()}  # v[0] is the most recent week
    days = [today + timedelta(days=i) for i in range(1, FORECAST_DAYS + 1)]
    daily = [(d, wd_avg.get(d.weekday(), 0.0)) for d in days]
    likely = sum(v for _, v in daily)
    spread = pstdev(weekly) * math.sqrt(FORECAST_DAYS / 7) if len(weekly) > 1 else 0.0
    low, high = max(likely - spread, 0.0), likely + spread
    recent4, before4 = sum(weekly[:4]), sum(weekly[4:])
    trend = pct_change(recent4, before4)
    sups = {s.id: s.name for s in db.query(Supplier).filter_by(merchant_id=m.id)}
    bills = db.query(Payable).filter(Payable.merchant_id == m.id, Payable.paid.is_(False), Payable.due_date <= today + timedelta(days=FORECAST_DAYS)).order_by(Payable.due_date).all()
    bills_total = round(sum(b.amount for b in bills), 2)

    def crunch(scale: float) -> dict | None:
        """Cumulative usable inflow vs cumulative bills; opening balance and other costs are unknown, so this is a timing check only."""
        inflow, due, worst, when = 0.0, 0.0, 0.0, None
        bi = 0
        for d, v in daily:
            inflow += v * scale * USABLE
            while bi < len(bills) and bills[bi].due_date <= d:
                due += bills[bi].amount
                bi += 1
            if due - inflow > worst:
                worst, when = due - inflow, d
        return {"date": when.isoformat(), "shortfall": round(worst, 2)} if when and worst > 0 else None
    low_scale = (low / likely) if likely else 0.0
    cl, cw = crunch(1.0), crunch(low_scale)
    fest = [{"name": f["name"], "days": f["days"]} for f in calendar.upcoming(m.segment, FORECAST_DAYS)[:2]]
    notes = ["Based on your last 8 weeks, by weekday. A range, not a promise.", "Bills are only those you recorded. Rent, salaries and other costs are not included unless added."]
    if fest:
        notes.append("Upcoming festivals can lift sales above this range: " + ", ".join(f["name"] for f in fest) + ".")
    return {"no_data": False, "horizon_days": FORECAST_DAYS, "from": days[0].isoformat(), "to": days[-1].isoformat(),
            "collections": {"low": round(low, 2), "likely": round(likely, 2), "high": round(high, 2)},
            "trend_pct": trend, "weekly_history": [round(w, 2) for w in reversed(weekly)],
            "bills": [{"label": b.note or sups.get(b.supplier_id, "Bill"), "amount": b.amount, "due_date": b.due_date.isoformat(),
                       "days": (b.due_date - today).days} for b in bills],
            "bills_total": bills_total, "net_likely": round(likely * USABLE - bills_total, 2), "net_low": round(low * USABLE - bills_total, 2),
            "crunch": cl, "crunch_if_low": cw,
            "working_capital_needed": cw["shortfall"] if cw else 0.0,
            "festivals": fest, "notes": notes}
