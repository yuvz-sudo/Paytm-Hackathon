"""GST helper: turnover, estimated tax collected by slab, and filing due dates.
Prices are treated as GST-inclusive (typical for retail). Un-itemised payments have no slab, so
they are reported separately instead of guessed."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import clock
from ..models import Item, Merchant, Transaction, TxnItem
from ..util import resolve_period

THRESHOLD_GOODS = 4_000_000  # Rs 40 lakh aggregate turnover (goods, most states)
THRESHOLD_SERVICES = 2_000_000  # Rs 20 lakh (services)


def _due_this_month(day: int, today: date) -> date:
    """Last month's return (monthly filers) is due on this month's 11th (GSTR-1) / 20th (GSTR-3B).
    The date may already have passed; we cannot know whether it was filed, so callers must say so."""
    return date(today.year, today.month, day)


def summary(db: Session, m: Merchant, period: str = "last_month") -> dict:
    start, end, label = resolve_period(period)
    txns = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.ts >= start, Transaction.ts < end,
                                        Transaction.status == "success").all()
    turnover = round(sum(t.amount for t in txns), 2)
    today = clock.today()
    base = {"period": label, "start": start.date().isoformat(), "end": (end - timedelta(seconds=1)).date().isoformat(),
            "turnover": turnover, "registered": m.gst_registered, "payments": len(txns)}
    # annualised turnover vs registration threshold (useful for unregistered merchants)
    last30 = clock.now() - timedelta(days=30)
    t30 = sum(x.amount for x in db.query(Transaction).filter(
        Transaction.merchant_id == m.id, Transaction.ts >= last30, Transaction.status == "success"))
    annual = t30 * 12
    limit = THRESHOLD_SERVICES if m.segment == "salon" else THRESHOLD_GOODS
    base["annualised_turnover"] = round(annual)
    base["registration_threshold"] = limit
    if not m.gst_registered:
        base["threshold_alert"] = annual >= 0.8 * limit
        base["threshold_crossed"] = annual >= limit
        base["no_data"] = not txns
        return base

    rates = {i.id: i.gst_rate for i in db.query(Item).filter_by(merchant_id=m.id)}
    slab: dict[float, float] = defaultdict(float)
    itemized_ids = [t.id for t in txns if t.itemized]
    allocated = 0.0
    for k in range(0, len(itemized_ids), 500):
        for ti in db.query(TxnItem).filter(TxnItem.txn_id.in_(itemized_ids[k:k + 500])):
            slab[rates.get(ti.item_id, 0.0)] += ti.amount
            allocated += ti.amount
    breakup = []
    tax_total = 0.0
    for rate in sorted(slab):
        gross = slab[rate]
        tax = gross * rate / (100 + rate)
        tax_total += tax
        breakup.append({"rate": rate, "sales": round(gross, 2), "taxable_value": round(gross - tax, 2), "tax": round(tax, 2)})
    unallocated = round(turnover - allocated, 2)
    base.update({
        "breakup": breakup, "estimated_tax": round(tax_total, 2), "unallocated_sales": unallocated,
        "unallocated_note": "Payments without item details have no GST slab; add them to your returns manually." if unallocated > 0.5 else None,
        "gstr1_due": _due_this_month(11, today).isoformat(), "gstr3b_due": _due_this_month(20, today).isoformat(),
        "days_to_gstr1": (_due_this_month(11, today) - today).days, "days_to_gstr3b": (_due_this_month(20, today) - today).days,
        "filing_note": "Dates shown are for last month's return (monthly filers). Quarterly (QRMP) filers have different dates.",
        "no_data": not txns,
        "disclaimer": "Estimate from Paytm payments for planning only. Confirm with your CA before filing.",
    })
    return base
