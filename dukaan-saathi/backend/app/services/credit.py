"""Cash-flow gap detection and an *indicative* credit suggestion.

We only suggest credit when there is a real gap (bills due before expected inflow covers them). The
offer is sized from verified settlement history and shown with its reasoning; the actual offer,
rate and approval belong to Paytm's lending partners. Illustrative parameters are named constants."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import clock
from ..models import Merchant, Payable, Settlement, Supplier, Transaction

HORIZON_DAYS = 14
INDICATIVE_APR = 0.18  # illustrative only
TENOR_MONTHS = 6
MAX_LIMIT_MULTIPLE = 0.6  # of average monthly inflow
MIN_HISTORY_DAYS = 30
MIN_ACTIVE_DAY_RATIO = 0.6


def _daily_totals(db: Session, m: Merchant, days: int) -> dict:
    today = clock.today()
    start = datetime(today.year, today.month, today.day) - timedelta(days=days)
    end = datetime(today.year, today.month, today.day)
    tot: dict = {}
    for t in db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.ts >= start, Transaction.ts < end,
                                          Transaction.status == "success"):
        tot[t.ts.date()] = tot.get(t.ts.date(), 0.0) + t.amount
    return tot


def cashflow(db: Session, m: Merchant) -> dict:
    today = clock.today()
    daily = _daily_totals(db, m, 28)
    first_txn = db.query(Transaction.ts).filter_by(merchant_id=m.id).order_by(Transaction.ts).first()
    history_days = (today - first_txn[0].date()).days if first_txn else 0
    avg_daily = sum(daily.values()) / 28 if daily else 0.0
    # median of the last 7 complete days is robust to a single spike (festival, bulk order)
    recent = sorted(daily.get(today - timedelta(days=i), 0.0) for i in range(1, 8))
    last7 = recent[3]
    # use the more cautious of the 28-day average and the recent median for expected inflow
    pace = min(avg_daily, last7) if last7 > 0 else avg_daily
    pending = sum(s.amount for s in db.query(Settlement).filter_by(merchant_id=m.id, status="pending"))
    payables = db.query(Payable).filter(Payable.merchant_id == m.id, Payable.paid.is_(False),
                                        Payable.due_date <= today + timedelta(days=HORIZON_DAYS)).order_by(Payable.due_date).all()
    sups = {s.id: s.name for s in db.query(Supplier).filter_by(merchant_id=m.id)}
    due_total = sum(p.amount for p in payables)
    usable = pace * 0.85  # keep ~15% of inflow for running costs not tracked here
    expected_inflow = usable * HORIZON_DAYS
    # Timing matters: a bill due on day 4 cannot be paid from sales that arrive on day 10. Check the
    # shortfall at each due date cumulatively and take the worst one.
    gap, running = 0.0, 0.0
    for p in payables:
        running += p.amount
        gap = max(gap, running - usable * max(0, (p.due_date - today).days))
    return {
        "horizon_days": HORIZON_DAYS, "avg_daily_inflow": round(avg_daily, 2), "recent_daily_inflow": round(last7, 2),
        "expected_inflow": round(expected_inflow, 2), "pending_settlements": round(pending, 2),
        "bills_due": [{"label": p.note or sups.get(p.supplier_id, "Bill"), "amount": p.amount, "due_date": p.due_date.isoformat(),
                       "days": (p.due_date - today).days} for p in payables],
        "bills_due_total": round(due_total, 2), "gap": round(gap, 2), "has_gap": gap > 0,
        "history_days": history_days, "no_data": not daily,
    }


def suggestion(db: Session, m: Merchant) -> dict:
    cf = cashflow(db, m)
    if cf["no_data"] or cf["history_days"] < MIN_HISTORY_DAYS:
        return {"cashflow": cf, "eligible": False, "reason": "not_enough_history", "needs_credit": False}
    daily = _daily_totals(db, m, 28)
    active_ratio = len([v for v in daily.values() if v > 0]) / 28
    monthly = cf["avg_daily_inflow"] * 30
    reasons = [f"Average monthly Paytm inflow about ₹{round(monthly):,}", f"Active on {round(active_ratio * 28)} of last 28 days"]
    if active_ratio < MIN_ACTIVE_DAY_RATIO:
        return {"cashflow": cf, "eligible": False, "reason": "low_activity", "needs_credit": cf["has_gap"], "reasons": reasons}
    limit = round(monthly * MAX_LIMIT_MULTIPLE / 1000) * 1000
    amount = min(limit, max(10000, round(cf["gap"] * 1.1 / 1000) * 1000)) if cf["has_gap"] else 0
    r = INDICATIVE_APR / 12
    emi = round(amount * r / (1 - (1 + r) ** -TENOR_MONTHS)) if amount else 0
    out = {"cashflow": cf, "eligible": True, "needs_credit": cf["has_gap"], "max_limit": limit, "reasons": reasons,
           "suggested_amount": amount, "tenor_months": TENOR_MONTHS, "indicative_apr_pct": INDICATIVE_APR * 100,
           "indicative_emi": emi, "covers_gap": amount >= cf["gap"] if cf["has_gap"] else None,
           "disclaimer": "Indicative only. Final eligibility, rate and terms are decided by Paytm's lending partner."}
    if not cf["has_gap"]:
        out["note"] = "No cash gap in the next 14 days, so no credit is needed right now."
    return out
