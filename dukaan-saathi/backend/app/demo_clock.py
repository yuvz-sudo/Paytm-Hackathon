"""Keep sample data current, so a demo never goes stale.

Sample data is generated relative to the day it was created. Days later, "today" and "yesterday" would be empty and every
deadline in the story (a chargeback due in 1 day, a late settlement) would be in the past. On the first request each
day, a sample-data merchant's history is moved forward by the days that passed, and today's payments are filled in up to
the current time. Only merchants with sample_data=True are touched: real merchants' records are never changed."""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import clock
from .models import Briefing, Chargeback, Customer, Item, LedgerEntry, Merchant, Payable, Review, Settlement, Transaction, TxnItem

log = logging.getLogger("dukaan.demo")

# Story data that moves with the calendar. Things the merchant did (actions, messages, audit log, campaigns) stay put.
SHIFT: list[tuple[type, tuple[str, ...]]] = [
    (Transaction, ("ts",)), (Customer, ("created_at",)), (Review, ("ts",)), (Settlement, ("expected_date", "settled_date")),
    (Item, ("stock_reported_at",)), (LedgerEntry, ("ts", "due_date")), (Payable, ("due_date",)), (Chargeback, ("raised_date", "proof_due_date")),
]
THROTTLE_SECONDS = 120
_lock = threading.Lock()
_checked: dict[int, float] = {}


def _spec(m: Merchant) -> dict:
    from .seed import MERCHANTS, sample_spec_for
    return next((s for s in MERCHANTS if s["phone"] == m.phone and s["name"] == m.name), None) or sample_spec_for(m.segment)


def shift(db: Session, m: Merchant, days: int) -> None:
    delta = timedelta(days=days)
    for model, cols in SHIFT:
        for row in db.query(model).filter(model.merchant_id == m.id):
            for c in cols:
                v = getattr(row, c)
                if v is not None:
                    setattr(row, c, v + delta)
    db.query(Briefing).filter_by(merchant_id=m.id).delete()


def top_up(db: Session, m: Merchant, since: datetime, now: datetime) -> int:
    """Simulated payments in (since, now], same shape as the seed. Deterministic per day, so repeated calls never
    duplicate or contradict each other."""
    from .seed import _festival_factor, _hour_weights, _pick_items, _weekday_factor
    spec = _spec(m)
    items = db.query(Item).filter_by(merchant_id=m.id, active=True).all()
    rates = {row[0]: row[5] for row in spec["items"]}
    weights = [rates.get(it.name, 1.0) for it in items]
    recent = now - timedelta(days=30)
    regulars = [c for (c,) in db.query(Transaction.customer_id).filter(Transaction.merchant_id == m.id, Transaction.ts >= recent,
                                                                         Transaction.customer_id.isnot(None)).distinct()]
    hw = _hour_weights(spec["segment"], *spec["hours"])
    hours, hweights = list(hw), list(hw.values())
    added = 0
    d = since.date()
    while d <= now.date():
        rng = random.Random(spec["seed"] * 1000 + d.toordinal())
        f = _weekday_factor(spec["segment"], d) * _festival_factor(spec["segment"], d, now.date())
        n = max(0, int(rng.gauss(spec["daily"] * f, spec["daily"] * 0.07)))
        for _ in range(n):
            h = rng.choices(hours, weights=hweights)[0]
            ts = datetime(d.year, d.month, d.day, h, rng.randint(0, 59), rng.randint(0, 59))
            cust = rng.choice(regulars) if regulars and rng.random() < 0.38 else None
            roll = rng.random()
            status = "failed" if roll < 0.025 else "refunded" if roll < 0.033 else "success"
            mode = rng.choices(["UPI", "CARD", "WALLET"], weights=[88, 7, 5])[0]
            itemized = bool(items) and rng.random() < spec["itemized"]
            picks = _pick_items(rng, items, weights, spec["segment"]) if itemized else []
            lo, hi = spec["avg_untemized"]
            amount = float(round(rng.uniform(lo, hi) / 5) * 5)
            if not (since < ts <= now):
                continue  # draw the same random numbers either way so each day stays reproducible
            t = Transaction(merchant_id=m.id, customer_id=cust, ts=ts, status=status, mode=mode, itemized=itemized, amount=amount)
            if picks:
                t.amount = round(sum(it.price * q for it, q in picks), 2)
                for it, q in picks:
                    t.items.append(TxnItem(item_id=it.id, qty=q, amount=round(it.price * q, 2)))
            db.add(t)
            added += 1
        d += timedelta(days=1)
    return added


def refresh(db: Session, m: Merchant, force: bool = False) -> None:
    """Called on requests; cheap when there is nothing to do. Never raises."""
    if not m.sample_data:
        return
    now_s = time.monotonic()
    if not force and now_s - _checked.get(m.id, -1e9) < THROTTLE_SECONDS:
        return
    with _lock:
        _checked[m.id] = now_s
        try:
            now = clock.now()
            last = db.query(func.max(Transaction.ts)).filter(Transaction.merchant_id == m.id).scalar()
            if last is None:
                return  # sample data was removed
            if isinstance(last, str):
                last = datetime.fromisoformat(last)
            days = (now.date() - last.date()).days
            if days > 0:
                shift(db, m, days)
                db.flush()
                # data made late in the evening would now sit later today than the current time: drop those payments
                keep = {i for (i,) in db.query(Chargeback.txn_id).filter(Chargeback.merchant_id == m.id, Chargeback.txn_id.isnot(None))}
                future = [i for (i,) in db.query(Transaction.id).filter(Transaction.merchant_id == m.id, Transaction.ts > now) if i not in keep]
                for k in range(0, len(future), 500):
                    db.query(TxnItem).filter(TxnItem.txn_id.in_(future[k:k + 500])).delete(synchronize_session=False)
                    db.query(Transaction).filter(Transaction.id.in_(future[k:k + 500])).delete(synchronize_session=False)
                last = db.query(func.max(Transaction.ts)).filter(Transaction.merchant_id == m.id).scalar() or now
                if isinstance(last, str):
                    last = datetime.fromisoformat(last)
                log.info("sample data for merchant %s moved forward %s day(s)", m.id, days)
            if last > now:  # clock went backwards (tests / FAKE_NOW): leave the data alone
                db.commit()
                return
            n = top_up(db, m, last, now) if (now - last) > timedelta(minutes=5) else 0
            if days > 0 or n:
                db.commit()
        except Exception as e:  # a demo nicety must never break a real request
            log.exception("demo refresh failed: %s", e)
            db.rollback()
