"""Udhaar (credit-sale) book. Payments are applied FIFO to the oldest credit so ageing is honest."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import clock, messages
from ..models import Customer, LedgerEntry, Merchant
from ..util import best_match, inr
from . import actions, audit, briefing

MAX_AMOUNT = 10_000_000


def balance(db: Session, mid: int, cid: int) -> float:
    b = 0.0
    for e in db.query(LedgerEntry).filter_by(merchant_id=mid, customer_id=cid):
        b += e.amount if e.kind == "credit_given" else -e.amount
    return round(b, 2)


def _open_credits(entries: list[LedgerEntry]) -> list[tuple[LedgerEntry, float]]:
    paid = sum(e.amount for e in entries if e.kind == "payment_received")
    open_: list[tuple[LedgerEntry, float]] = []
    for e in sorted((e for e in entries if e.kind == "credit_given"), key=lambda x: x.ts):
        take = min(paid, e.amount)
        paid -= take
        rem = e.amount - take
        if rem > 0.005:
            open_.append((e, rem))
    return open_


def dues(db: Session, m: Merchant, min_amount: float = 0.0) -> dict:
    today = clock.today()
    by_c: dict[int, list[LedgerEntry]] = defaultdict(list)
    for e in db.query(LedgerEntry).filter_by(merchant_id=m.id):
        by_c[e.customer_id].append(e)
    custs = {c.id: c for c in db.query(Customer).filter_by(merchant_id=m.id)}
    rows, buckets = [], {"0-30": 0.0, "31-60": 0.0, "60+": 0.0}
    for cid, entries in by_c.items():
        open_ = _open_credits(entries)
        total = round(sum(r for _, r in open_), 2)
        if total <= min_amount or cid not in custs:
            continue
        oldest = min(e.ts.date() for e, _ in open_)
        age = (today - oldest).days
        overdue = round(sum(r for e, r in open_ if e.due_date and e.due_date < today), 2)
        for e, r in open_:
            a = (today - e.ts.date()).days
            buckets["0-30" if a <= 30 else "31-60" if a <= 60 else "60+"] += r
        rows.append({"customer_id": cid, "name": custs[cid].name, "phone": custs[cid].phone, "outstanding": total,
                     "overdue": overdue, "oldest_days": age, "do_not_contact": custs[cid].do_not_contact})
    rows.sort(key=lambda r: (r["overdue"], r["oldest_days"]), reverse=True)
    return {"total_outstanding": round(sum(r["outstanding"] for r in rows), 2), "customers": rows,
            "aging": {k: round(v, 2) for k, v in buckets.items()}, "count": len(rows),
            "total_overdue": round(sum(r["overdue"] for r in rows), 2)}


def find_customer(db: Session, m: Merchant, name: str) -> tuple[Customer | None, list[Customer]]:
    custs = db.query(Customer).filter_by(merchant_id=m.id).all()
    key, _, amb = best_match(name, {str(c.id): [c.name, c.name.split()[0]] for c in custs}, cutoff=0.8)
    by_id = {str(c.id): c for c in custs}
    if amb:
        return None, [by_id[k] for k in amb]
    return (by_id[key] if key else None), []


def _candidate(db: Session, m: Merchant, c: Customer) -> dict:
    """Enough to tell two people with the same name apart."""
    tail = re.sub(r"\D", "", c.phone or "")[-4:]
    return {"id": c.id, "name": c.name, "phone_hint": f"…{tail}" if tail else None, "balance": balance(db, m.id, c.id),
            "label": c.name + (f" (…{tail})" if tail else f" (#{c.id})")}


def resolve(db: Session, m: Merchant, name: str | None, customer_id: int | None = None) -> tuple[Customer | None, dict | None]:
    """A customer by id (exact, from a button) or by name (typed / spoken). Returns (customer, error)."""
    if customer_id is not None:
        c = db.query(Customer).filter_by(id=customer_id, merchant_id=m.id).first()
        return (c, None) if c else (None, {"ok": False, "error": "customer_not_found", "name": name or ""})
    c, amb = find_customer(db, m, name or "")
    if amb:
        return None, {"ok": False, "error": "ambiguous_customer", "candidates": [_candidate(db, m, x) for x in amb]}
    return c, None


def _validate_amount(amount) -> str | None:
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return "invalid_amount"
    if math.isnan(a) or a <= 0 or a > MAX_AMOUNT:
        return "invalid_amount"
    return None


def add_credit(db: Session, m: Merchant, customer_name: str, amount: float, note: str = "", due_in_days: int = 15,
               create_if_missing: bool = False, customer_id: int | None = None) -> dict:
    err = _validate_amount(amount)
    if err:
        return {"ok": False, "error": err}
    c, bad = resolve(db, m, customer_name, customer_id)
    if bad and bad["error"] == "ambiguous_customer":
        return bad
    if customer_id is not None and not c:
        return bad
    if not c:
        if not create_if_missing:
            return {"ok": False, "error": "customer_not_found", "name": customer_name, "can_create": True}
        c = Customer(merchant_id=m.id, name=customer_name.strip().title()[:80], created_at=clock.now())
        db.add(c)
        db.flush()
    now = clock.now()
    db.add(LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="credit_given", amount=float(amount), ts=now,
                       due_date=(now + timedelta(days=max(1, min(int(due_in_days), 365)))).date(), note=note[:200]))
    audit.log(db, m.id, "merchant", "udhaar_added", {"customer_id": c.id, "amount": amount})
    briefing.invalidate(db, m.id)
    db.commit()
    return {"ok": True, "customer": c.name, "customer_id": c.id, "added": float(amount), "balance": balance(db, m.id, c.id)}


def record_payment(db: Session, m: Merchant, customer_name: str, amount: float, customer_id: int | None = None) -> dict:
    err = _validate_amount(amount)
    if err:
        return {"ok": False, "error": err}
    c, bad = resolve(db, m, customer_name, customer_id)
    if bad:
        return bad
    if not c:
        return {"ok": False, "error": "customer_not_found", "name": customer_name}
    bal = balance(db, m.id, c.id)
    if bal <= 0:
        return {"ok": False, "error": "nothing_due", "customer": c.name}
    if float(amount) > bal + 0.5:
        return {"ok": False, "error": "exceeds_balance", "customer": c.name, "balance": bal}
    db.add(LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="payment_received", amount=float(amount), ts=clock.now(), note="payment"))
    audit.log(db, m.id, "merchant", "udhaar_payment", {"customer_id": c.id, "amount": amount})
    briefing.invalidate(db, m.id)
    db.commit()
    return {"ok": True, "customer": c.name, "customer_id": c.id, "received": float(amount), "balance": balance(db, m.id, c.id)}


def propose_reminders(db: Session, m: Merchant, customer_name: str | None = None, min_overdue_days: int = 7, limit: int = 5,
                      customer_id: int | None = None) -> dict:
    d = dues(db, m)
    rows = d["customers"]
    if customer_name or customer_id is not None:
        c, bad = resolve(db, m, customer_name, customer_id)
        if bad:
            return bad
        if not c:
            return {"ok": False, "error": "customer_not_found", "name": customer_name}
        rows = [r for r in rows if r["customer_id"] == c.id]
        if not rows:
            return {"ok": False, "error": "nothing_due", "customer": c.name}
    else:
        rows = [r for r in rows if r["oldest_days"] >= min_overdue_days and r["overdue"] > 0]
    proposals, skipped = [], []
    for r in rows[:limit]:
        if r["do_not_contact"]:
            skipped.append({"name": r["name"], "reason": "opted_out"})
            continue
        if not r["phone"]:
            skipped.append({"name": r["name"], "reason": "no_phone"})
            continue
        msg = messages.udhaar_reminder(m.language, m.name, r["name"], r["outstanding"], r["oldest_days"])
        a = actions.propose(
            db, m, "udhaar_reminder", f"Remind {r['name']} about {inr(r['outstanding'])}",
            {"customer_id": r["customer_id"], "name": r["name"], "phone": r["phone"], "amount": r["outstanding"],
             "overdue_days": r["oldest_days"], "message": msg},
            dedupe_key=f"udhaar:{r['customer_id']}")
        proposals.append(a)
    return {"ok": True, "proposals": proposals, "skipped": skipped, "total_candidates": len(rows)}


def customer_balance(db: Session, m: Merchant, name: str) -> dict:
    c, amb = find_customer(db, m, name)
    if amb:
        return {"ok": False, "error": "ambiguous_customer", "candidates": [_candidate(db, m, x) for x in amb]}
    if not c:
        return {"ok": False, "error": "customer_not_found", "name": name}
    row = next((r for r in dues(db, m)["customers"] if r["customer_id"] == c.id), None)
    if not row:
        return {"ok": True, "customer": c.name, "outstanding": 0.0, "overdue": 0.0, "oldest_days": 0}
    return {"ok": True, "customer": c.name, "outstanding": row["outstanding"], "overdue": row["overdue"], "oldest_days": row["oldest_days"]}
