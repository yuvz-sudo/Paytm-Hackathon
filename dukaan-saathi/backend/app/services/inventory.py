"""Stock-out prediction.

The merchant tells us stock occasionally (voice note / app). Current stock is estimated as
last_reported - units sold (from itemised Paytm payments) since that report. Because some payments
are not itemised, sales pace is a lower bound; we scale it by itemisation coverage so we do not
under-warn, and we expose the confidence to the merchant.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import clock
from ..models import Item, Merchant, Supplier, Transaction, TxnItem
from ..util import best_match, qty_fmt

VELOCITY_WINDOW_DAYS = 14
COVER_DAYS = 7  # how many days of sales a re-order should cover beyond lead time


def _sold_between(db: Session, mid: int, start: datetime, end: datetime) -> tuple[dict[int, float], float]:
    """Returns (qty per item from itemised successful payments, itemisation coverage 0..1)."""
    ok = db.query(Transaction.id, Transaction.itemized).filter(
        Transaction.merchant_id == mid, Transaction.ts >= start, Transaction.ts < end, Transaction.status == "success").all()
    if not ok:
        return {}, 0.0
    coverage = sum(1 for _, it in ok if it) / len(ok)
    ids = [i for i, it in ok if it]
    qty: dict[int, float] = defaultdict(float)
    for k in range(0, len(ids), 500):
        for ti in db.query(TxnItem).filter(TxnItem.txn_id.in_(ids[k:k + 500])):
            qty[ti.item_id] += ti.qty
    return qty, coverage


def stock_status(db: Session, m: Merchant, only_risky: bool = False) -> dict:
    now = clock.now()
    start = now - timedelta(days=VELOCITY_WINDOW_DAYS)
    sold14, coverage = _sold_between(db, m.id, start, now)
    items = db.query(Item).filter_by(merchant_id=m.id, active=True, track_stock=True).all()
    suppliers = {s.id: s for s in db.query(Supplier).filter_by(merchant_id=m.id)}
    # lower-bound correction: scale pace up by 1/coverage, capped so one odd day can't explode it
    scale = 1 / max(coverage, 0.5) if coverage else 1.0
    out = []
    for it in items:
        row = {"item_id": it.id, "item": it.name, "unit": it.unit, "supplier": None}
        sup = suppliers.get(it.supplier_id)
        if sup:
            row["supplier"] = {"id": sup.id, "name": sup.name, "lead_time_days": sup.lead_time_days}
        pace = sold14.get(it.id, 0.0) / VELOCITY_WINDOW_DAYS * scale
        row["daily_pace"] = round(pace, 2)
        row["daily_revenue"] = round(pace * it.price, 2)
        if it.stock_qty is None or it.stock_reported_at is None:
            row.update(status="unknown", days_left=None, current_stock=None, note="stock never reported")
            out.append(row)
            continue
        sold_since, _ = _sold_between(db, m.id, it.stock_reported_at, now)
        current = max(0.0, it.stock_qty - sold_since.get(it.id, 0.0) * scale)
        row["current_stock"] = round(current, 1)
        row["reported_days_ago"] = (now - it.stock_reported_at).days
        if pace <= 0.0:
            row.update(status="no_sales", days_left=None)
        else:
            days_left = current / pace
            lead = sup.lead_time_days if sup else 2
            row["days_left"] = round(days_left, 1)
            if current <= 0:
                row["status"] = "out"
            elif days_left <= lead:
                row["status"] = "critical"  # will run out before a new order could arrive
            elif days_left <= lead + 3:
                row["status"] = "low"
            else:
                row["status"] = "ok"
        if row["status"] in ("out", "critical", "low"):
            lead = sup.lead_time_days if sup else 2
            need = pace * (lead + (it.cover_days or COVER_DAYS)) - current
            pack = it.pack_qty or 1
            row["suggested_qty"] = max(pack, math.ceil(max(need, 0) / pack) * pack)
        if row.get("reported_days_ago", 0) > 10 and row["status"] != "out":
            row["stale"] = True  # estimate is based on an old report; ask merchant to refresh
        out.append(row)
    order = {"out": 0, "critical": 1, "low": 2, "unknown": 3, "ok": 4, "no_sales": 5}
    out.sort(key=lambda r: (order[r["status"]], r["days_left"] if r.get("days_left") is not None else 1e9))
    if only_risky:
        out = [r for r in out if r["status"] in ("out", "critical", "low")]
    return {"items": out, "coverage_pct": round(coverage * 100), "tracks_stock": bool(items)}


def find_item(db: Session, m: Merchant, name: str) -> tuple[Item | None, list[Item]]:
    items = db.query(Item).filter_by(merchant_id=m.id, active=True).all()
    key, _, amb = best_match(name, {str(i.id): [i.name, *(i.aliases or [])] for i in items})
    by_id = {str(i.id): i for i in items}
    if amb:
        return None, [by_id[k] for k in amb]
    return (by_id[key] if key else None), []


def update_stock(db: Session, m: Merchant, item_name: str, quantity: float, mode: str = "set") -> dict:
    """mode 'set' = the merchant counted this many; 'add' = new stock arrived."""
    if quantity is None or quantity < 0 or math.isnan(float(quantity)) or quantity > 1_000_000:
        return {"ok": False, "error": "invalid_quantity"}
    it, amb = find_item(db, m, item_name)
    if amb:
        return {"ok": False, "error": "ambiguous_item", "candidates": [i.name for i in amb]}
    if not it:
        return {"ok": False, "error": "item_not_found", "item": item_name}
    if not it.track_stock:
        return {"ok": False, "error": "item_not_stock_tracked", "item": it.name}
    now = clock.now()
    if mode == "add":
        cur = stock_status(db, m)
        row = next((r for r in cur["items"] if r["item_id"] == it.id), None)
        base = row["current_stock"] if row and row.get("current_stock") is not None else 0.0
        new_qty = base + quantity
    else:
        new_qty = quantity
    it.stock_qty, it.stock_reported_at = round(new_qty, 2), now
    from . import briefing
    briefing.invalidate(db, m.id)
    db.commit()
    return {"ok": True, "item": it.name, "unit": it.unit, "stock": round(new_qty, 2), "text": f"{it.name}: {qty_fmt(new_qty)} {it.unit}"}


def item_report(db: Session, m: Merchant, item_name: str) -> dict:
    it, amb = find_item(db, m, item_name)
    if amb:
        return {"ok": False, "error": "ambiguous_item", "candidates": [i.name for i in amb]}
    if not it:
        return {"ok": False, "error": "item_not_found", "item": item_name}
    now = clock.now()
    cur, _ = _sold_between(db, m.id, now - timedelta(days=7), now)
    prev, _ = _sold_between(db, m.id, now - timedelta(days=14), now - timedelta(days=7))
    q7, q14 = cur.get(it.id, 0.0), prev.get(it.id, 0.0)
    out = {"ok": True, "item": it.name, "unit": it.unit, "price": it.price, "tracked": it.track_stock,
           "qty_7d": round(q7, 1), "qty_prev_7d": round(q14, 1), "revenue_7d": round(q7 * it.price),
           "trend_pct": round((q7 - q14) / q14 * 100) if q14 else None}
    if it.track_stock:
        row = next((r for r in stock_status(db, m)["items"] if r["item_id"] == it.id), None)
        out["stock"] = row
    return out
