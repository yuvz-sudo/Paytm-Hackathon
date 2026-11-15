"""Counter-fraud nudge. We cannot judge whether a screenshot is genuine; we can check whether the money is in the
merchant's own Paytm records. Only a credit in those records (or the soundbox announcement) counts as payment."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from .. import clock
from ..models import Customer, Merchant, Transaction

HELPLINE = "1930"
LOOKBACK_HOURS = 24


def _row(t: Transaction, now) -> dict:
    return {"id": t.id, "amount": round(t.amount, 2), "mode": t.mode, "status": t.status, "ts": t.ts.isoformat(),
            "minutes_ago": max(0, int((now - t.ts).total_seconds() // 60))}


def verify(db: Session, m: Merchant, amount: float, minutes: int = 5) -> dict:
    """Is there a successful payment of exactly this amount in the last `minutes` minutes?"""
    if not (0 < amount <= 10_000_000) or not (1 <= minutes <= 120):
        return {"ok": False, "error": "invalid_input"}
    now = clock.now()
    rows = db.query(Transaction).filter(
        Transaction.merchant_id == m.id, Transaction.amount.between(amount - 0.005, amount + 0.005),
        Transaction.ts >= now - timedelta(hours=LOOKBACK_HOURS), Transaction.ts <= now).order_by(Transaction.ts.desc()).all()
    window = now - timedelta(minutes=minutes)
    recent_ok = [t for t in rows if t.status == "success" and t.ts >= window]
    recent_other = [t for t in rows if t.status != "success" and t.ts >= window]
    earlier_ok = [t for t in rows if t.status == "success" and t.ts < window]
    if recent_ok:
        verdict = "received"
    elif recent_other:
        verdict = "not_received_" + recent_other[0].status  # failed | refunded
    elif earlier_ok:
        verdict = "earlier_only"
    else:
        verdict = "not_found"
    return {"ok": True, "amount": round(amount, 2), "window_minutes": minutes, "received": verdict == "received", "verdict": verdict,
            "matches": [_row(t, now) for t in recent_ok], "other_status": [_row(t, now) for t in recent_other],
            "earlier": [_row(t, now) for t in earlier_ok[:3]], "helpline": HELPLINE,
            "advice": "Confirm only from your Paytm app or soundbox. A screenshot can be edited. If you suspect fraud, call 1930."}


DAYS = {"today": 0, "yesterday": 1}


def today(db: Session, m: Merchant, day: str = "today") -> dict:
    """One day's payments, newest first, like the Paytm for Business transactions list (today or yesterday).
    Totals count successful payments only; failed and refunded rows are listed but never added in."""
    now = clock.now()
    back = DAYS.get(day, 0)
    start = clock.day_start(now.date()) - timedelta(days=back)
    end = now if back == 0 else start + timedelta(days=1)
    rows = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.ts >= start, Transaction.ts <= end if back == 0 else Transaction.ts < end) \
        .order_by(Transaction.ts.desc(), Transaction.id.desc()).all()
    names = {c.id: c.name for c in db.query(Customer).filter(Customer.id.in_({t.customer_id for t in rows if t.customer_id}))} if rows else {}
    ok = [t for t in rows if t.status == "success"]
    by_mode: dict[str, float] = {}
    for t in ok:
        by_mode[t.mode] = round(by_mode.get(t.mode, 0) + t.amount, 2)
    return {
        "day": day if day in DAYS else "today", "date": start.date().isoformat(), "as_of": (now if back == 0 else end).isoformat(), "complete": back > 0,
        "total": round(sum(t.amount for t in ok), 2), "count": len(ok),
        "failed_count": sum(t.status == "failed" for t in rows), "refund_count": sum(t.status == "refunded" for t in rows),
        "refund_amount": round(sum(t.amount for t in rows if t.status == "refunded"), 2), "by_mode": by_mode,
        "transactions": [{"id": t.id, "ts": t.ts.isoformat(), "amount": round(t.amount, 2), "mode": t.mode, "status": t.status,
                          "customer": names.get(t.customer_id)} for t in rows],
        "no_data": not rows,
    }
