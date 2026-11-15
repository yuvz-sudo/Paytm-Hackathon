"""UPI merchant-fee (MDR) estimate.

Rule as reported (NPCI framework, effective 15 Oct 2026; sourced from press coverage, not the circular itself):
  * 0.4% MDR on person-to-merchant UPI payments above Rs 2,000, capped at Rs 300 (reached at Rs 75,000).
  * Small merchants receiving up to Rs 1 lakh a month through UPI QR stay at zero.
  * Payments up to Rs 2,000 are not charged. Some categories (rail, telecom, insurance, fuel) pay a flat Rs 5; not modelled.
Our data has no QR-vs-other flag, so every UPI receipt is treated as QR. The result is always an estimate."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from .. import clock
from ..models import Merchant, Transaction
from ..util import resolve_period

MDR_RATE = 0.004
MDR_CAP = 300.0
PER_TXN_FREE_UPTO = 2000.0
MONTHLY_QR_EXEMPT = 100_000.0
EFFECTIVE_FROM = "2026-10-15"

ASSUMPTIONS = [
    "Every UPI receipt is treated as a QR payment (your data has no QR / other flag).",
    "If a calendar month's UPI receipts go above ₹1,00,000, payments above ₹2,000 in that month are charged 0.4% (max ₹300 each).",
    "Flat ₹5 categories (rail, telecom, insurance, fuel) are not modelled. Card and wallet fees are separate.",
    "Press-reported rule effective 15 Oct 2026. Confirm with your Paytm plan before relying on it.",
]


def _month_start(d: datetime) -> datetime:
    return datetime(d.year, d.month, 1)


def _next_month(d: datetime) -> datetime:
    return datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)


def mdr_estimate(db: Session, m: Merchant, period: str | None = "this_month") -> dict:
    start, end, label = resolve_period(period if period else "this_month")
    rows = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.mode == "UPI", Transaction.status == "success",
                                        Transaction.ts >= start, Transaction.ts < end).all()
    base = {"period": label, "start": start.isoformat(), "end": end.isoformat(), "estimate": True, "assumptions": ASSUMPTIONS,
            "rule": {"rate_pct": MDR_RATE * 100, "applies_above": PER_TXN_FREE_UPTO, "cap_per_txn": MDR_CAP,
                     "monthly_exempt_upto": MONTHLY_QR_EXEMPT, "effective_from": EFFECTIVE_FROM}}
    if not rows:
        return {**base, "no_data": True, "upi_receipts": 0.0, "upi_count": 0, "exempt_amount": 0.0, "chargeable_amount": 0.0,
                "chargeable_count": 0, "estimated_mdr": 0.0, "share_charged_pct": 0.0, "months": []}
    # the exemption is judged on the whole calendar month, even when the requested period covers only part of it
    month_totals: dict[datetime, float] = defaultdict(float)
    cur = _month_start(start)
    while cur < end:
        nxt = _next_month(cur)
        for (amt,) in db.query(Transaction.amount).filter(
                Transaction.merchant_id == m.id, Transaction.mode == "UPI", Transaction.status == "success",
                Transaction.ts >= cur, Transaction.ts < min(nxt, clock.now())):
            month_totals[cur] += amt
        cur = nxt
    chargeable_amt = 0.0
    chargeable_n = 0
    mdr = 0.0
    for t in rows:
        over = month_totals[_month_start(t.ts)] > MONTHLY_QR_EXEMPT
        if over and t.amount > PER_TXN_FREE_UPTO:
            chargeable_amt += t.amount
            chargeable_n += 1
            mdr += min(t.amount * MDR_RATE, MDR_CAP)
    total = round(sum(t.amount for t in rows), 2)
    months = [{"month": k.strftime("%Y-%m"), "upi_receipts": round(v, 2), "over_exempt_limit": v > MONTHLY_QR_EXEMPT,
               "headroom": round(max(MONTHLY_QR_EXEMPT - v, 0), 2)} for k, v in sorted(month_totals.items())]
    return {**base, "no_data": False, "upi_receipts": total, "upi_count": len(rows), "exempt_amount": round(total - chargeable_amt, 2),
            "chargeable_amount": round(chargeable_amt, 2), "chargeable_count": chargeable_n, "estimated_mdr": round(mdr, 2),
            "share_charged_pct": round(chargeable_amt / total * 100, 1) if total else 0.0, "months": months}
