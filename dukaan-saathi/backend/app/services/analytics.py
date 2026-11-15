"""Sales analytics computed from Paytm payments. All figures count only successful payments;
refunds and failures are reported separately so totals never silently include them."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy.orm import Session

from .. import clock
from ..models import Item, Merchant, Transaction, TxnItem
from ..util import pct_change, resolve_period


def _txns(db: Session, mid: int, start: datetime, end: datetime) -> list[Transaction]:
    return db.query(Transaction).filter(Transaction.merchant_id == mid, Transaction.ts >= start, Transaction.ts < end).all()


def sales_summary(db: Session, m: Merchant, period: str | None = "yesterday") -> dict:
    start, end, label = resolve_period(period)
    rows = _txns(db, m.id, start, end)
    ok = [t for t in rows if t.status == "success"]
    total = round(sum(t.amount for t in ok), 2)
    n = len(ok)
    refunds = [t for t in rows if t.status == "refunded"]
    failed = [t for t in rows if t.status == "failed"]
    by_mode: dict[str, float] = defaultdict(float)
    for t in ok:
        by_mode[t.mode] += t.amount
    days = max(1, (end - start).total_seconds() / 86400)
    # compare with the immediately preceding window of equal length (for "today" use same elapsed span yesterday)
    prev_start, prev_end = start - (end - start), start
    prev_total = sum(t.amount for t in _txns(db, m.id, prev_start, prev_end) if t.status == "success")
    attempts = len(ok) + len(failed)
    return {
        "period": label, "start": start.isoformat(), "end": end.isoformat(),
        "total": total, "payments": n, "avg_ticket": round(total / n, 2) if n else 0,
        "refund_count": len(refunds), "refund_amount": round(sum(t.amount for t in refunds), 2),
        "failed_count": len(failed), "failure_rate_pct": round(len(failed) / attempts * 100, 1) if attempts else 0,
        "by_mode": {k: round(v, 2) for k, v in by_mode.items()},
        "previous_total": round(prev_total, 2), "change_pct": pct_change(total, prev_total),
        "per_day_avg": round(total / days, 2),
        "no_data": n == 0,
    }


def daily_series(db: Session, m: Merchant, days: int = 30, include_today: bool = False) -> list[dict]:
    """Complete days only by default: today is still in progress and would look like a sales crash."""
    last = clock.today() if include_today else clock.today() - timedelta(days=1)
    start = datetime(last.year, last.month, last.day) - timedelta(days=days - 1)
    series = {(start + timedelta(days=i)).date(): [0.0, 0] for i in range(days)}
    for t in _txns(db, m.id, start, clock.now() + timedelta(seconds=1)):
        if t.status == "success" and t.ts.date() in series:
            series[t.ts.date()][0] += t.amount
            series[t.ts.date()][1] += 1
    return [{"date": d.isoformat(), "total": round(v[0], 2), "payments": v[1]} for d, v in sorted(series.items())]


def best_sellers(db: Session, m: Merchant, period: str | None = "last_7_days", limit: int = 5) -> dict:
    start, end, label = resolve_period(period)
    rows = _txns(db, m.id, start, end)
    ok = [t for t in rows if t.status == "success"]
    itemized = [t for t in ok if t.itemized]
    coverage = round(len(itemized) / len(ok) * 100) if ok else 0
    if not itemized:
        return {"period": label, "items": [], "slow_items": [], "coverage_pct": coverage, "no_data": True}
    ids = [t.id for t in itemized]
    names = {i.id: i for i in db.query(Item).filter_by(merchant_id=m.id)}
    qty: dict[int, float] = defaultdict(float)
    rev: dict[int, float] = defaultdict(float)
    for chunk_start in range(0, len(ids), 500):
        for ti in db.query(TxnItem).filter(TxnItem.txn_id.in_(ids[chunk_start:chunk_start + 500])):
            qty[ti.item_id] += ti.qty
            rev[ti.item_id] += ti.amount
    ranked = sorted(qty, key=lambda i: rev[i], reverse=True)
    out = [{"item": names[i].name, "unit": names[i].unit, "qty": round(qty[i], 1), "revenue": round(rev[i], 2)} for i in ranked[:limit]]
    # slow movers: active catalogue items with little or no sales in the window
    sold_ids = set(qty)
    slow = []
    for it in names.values():
        if it.active and it.id not in sold_ids:
            slow.append({"item": it.name, "qty": 0, "revenue": 0})
    tail = [{"item": names[i].name, "unit": names[i].unit, "qty": round(qty[i], 1), "revenue": round(rev[i], 2)} for i in ranked[-3:][::-1]]
    return {"period": label, "items": out, "slow_items": (slow + tail)[:3], "coverage_pct": coverage, "no_data": False}


def hourly_profile(db: Session, m: Merchant, days: int = 28) -> dict:
    today = clock.today()
    start = datetime(today.year, today.month, today.day) - timedelta(days=days)
    end = datetime(today.year, today.month, today.day)
    per_hour: dict[int, float] = defaultdict(float)
    for t in _txns(db, m.id, start, end):
        if t.status == "success":
            per_hour[t.ts.hour] += t.amount
    if not per_hour:
        return {"hours": [], "slow_hours": [], "peak_hours": [], "no_data": True}
    hrs = {h: round(v / days, 2) for h, v in per_hour.items()}
    open_hours = sorted(hrs)
    med = median(hrs.values())
    slow = [h for h in open_hours if hrs[h] < 0.55 * med]
    quietest = sorted(open_hours, key=lambda h: hrs[h])[:2]
    peak = sorted(open_hours, key=lambda h: hrs[h], reverse=True)[:3]
    return {"hours": [{"hour": h, "avg_revenue": hrs.get(h, 0.0)} for h in range(min(open_hours), max(open_hours) + 1)],
            "slow_hours": sorted(slow), "quietest_hours": sorted(quietest), "peak_hours": sorted(peak), "no_data": False}


def weekday_profile(db: Session, m: Merchant, weeks: int = 8) -> list[dict]:
    today = clock.today()
    start = datetime(today.year, today.month, today.day) - timedelta(days=7 * weeks)
    end = datetime(today.year, today.month, today.day)
    tot: dict[int, float] = defaultdict(float)
    for t in _txns(db, m.id, start, end):
        if t.status == "success":
            tot[t.ts.weekday()] += t.amount
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [{"day": names[i], "avg_revenue": round(tot[i] / weeks, 2)} for i in range(7)]


def anomalies(db: Session, m: Merchant) -> list[dict]:
    """Yesterday against the same weekday over the previous 4 weeks, plus payment-health checks."""
    out: list[dict] = []
    today = clock.today()
    y = today - timedelta(days=1)
    base = []
    for w in range(1, 5):
        d = y - timedelta(days=7 * w)
        s = datetime(d.year, d.month, d.day)
        base.append(sum(t.amount for t in _txns(db, m.id, s, s + timedelta(days=1)) if t.status == "success"))
    ys = datetime(y.year, y.month, y.day)
    ytxns = _txns(db, m.id, ys, ys + timedelta(days=1))
    ytotal = sum(t.amount for t in ytxns if t.status == "success")
    nonzero = [b for b in base if b > 0]
    if len(nonzero) >= 3:
        avg = median(nonzero)
        ch = pct_change(ytotal, avg)
        # a real dip must be well below the typical weekday AND below every one of the last 4 comparable days
        if ch is not None and ch <= -30 and ytotal < min(nonzero) * 0.95:
            out.append({"type": "sales_drop", "severity": "high" if ch <= -45 else "medium", "change_pct": ch,
                        "yesterday": round(ytotal), "typical": round(avg), "weekday": y.strftime("%A")})
        elif ch is not None and ch >= 50:
            out.append({"type": "sales_spike", "severity": "info", "change_pct": ch, "yesterday": round(ytotal),
                        "typical": round(avg), "weekday": y.strftime("%A")})
    ok = [t for t in ytxns if t.status == "success"]
    refunds = [t for t in ytxns if t.status == "refunded"]
    failed = [t for t in ytxns if t.status == "failed"]
    if len(ytxns) >= 20:
        if len(refunds) / len(ytxns) > 0.05:
            out.append({"type": "refund_spike", "severity": "medium", "count": len(refunds), "pct": round(len(refunds) / len(ytxns) * 100, 1)})
        if len(failed) / len(ytxns) > 0.08:
            out.append({"type": "payment_failures", "severity": "medium", "count": len(failed), "pct": round(len(failed) / len(ytxns) * 100, 1)})
    return out


def explain_change(db: Session, m: Merchant, day: str | None = None) -> dict:
    """Why was a day different? Compare with the same weekday last week and break the gap into
    footfall (payment count), basket size (average ticket), items and hours. Itemised data only for items."""
    today = clock.today()
    d = datetime.fromisoformat(day).date() if day else today - timedelta(days=1)
    ref = d - timedelta(days=7)

    def day_rows(x):
        s0 = datetime(x.year, x.month, x.day)
        return _txns(db, m.id, s0, s0 + timedelta(days=1))

    cur_all, ref_all = day_rows(d), day_rows(ref)
    cur = [t for t in cur_all if t.status == "success"]
    prev = [t for t in ref_all if t.status == "success"]
    ct, pt = sum(t.amount for t in cur), sum(t.amount for t in prev)
    if not prev or not cur:
        return {"no_data": True, "day": d.isoformat(), "weekday": d.strftime("%A")}
    out = {
        "no_data": False, "day": d.isoformat(), "weekday": d.strftime("%A"), "total": round(ct), "ref_total": round(pt),
        "change_pct": pct_change(ct, pt), "payments": len(cur), "ref_payments": len(prev),
        "payments_change_pct": pct_change(len(cur), len(prev)),
        "avg_ticket": round(ct / len(cur)), "ref_avg_ticket": round(pt / len(prev)),
        "ticket_change_pct": pct_change(ct / len(cur), pt / len(prev)),
        "failed": len([t for t in cur_all if t.status == "failed"]), "ref_failed": len([t for t in ref_all if t.status == "failed"]),
    }
    # hours with the biggest revenue swing
    hrs: dict[int, float] = defaultdict(float)
    for t in cur:
        hrs[t.ts.hour] += t.amount
    for t in prev:
        hrs[t.ts.hour] -= t.amount
    out["hour_swings"] = [{"hour": h, "delta": round(v)} for h, v in sorted(hrs.items(), key=lambda kv: abs(kv[1]), reverse=True)[:2]]

    # item swings (itemised payments only)
    names = {i.id: i.name for i in db.query(Item).filter_by(merchant_id=m.id)}
    delta: dict[int, float] = defaultdict(float)
    for rows, sign in ((cur, 1), (prev, -1)):
        ids = [t.id for t in rows if t.itemized]
        for k in range(0, len(ids), 500):
            for ti in db.query(TxnItem).filter(TxnItem.txn_id.in_(ids[k:k + 500])):
                delta[ti.item_id] += sign * ti.amount
    out["item_swings"] = [{"item": names[i], "delta": round(v)} for i, v in sorted(delta.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3] if abs(v) >= 50]
    # primary driver: whichever of footfall / basket explains more of the revenue change
    pc, tc = out["payments_change_pct"] or 0, out["ticket_change_pct"] or 0
    out["driver"] = "footfall" if abs(pc) >= abs(tc) else "basket"
    return out
