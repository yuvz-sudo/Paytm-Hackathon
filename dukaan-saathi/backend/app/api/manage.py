"""Manage the shop's records directly: customers (with phone numbers), catalogue items, and delivery of approved messages."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..models import Customer, Item, LedgerEntry, Merchant, Supplier, Transaction
from ..services import audit, auth, briefing, delivery, ledger
from .deps import current_merchant, need

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- customers

class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=20)
    do_not_contact: bool = False


class CustomerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=20)
    do_not_contact: bool | None = None


def _phone(db: Session, m: Merchant, raw: str, exclude_id: int | None = None) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        phone = auth.normalize_phone(raw)
    except auth.AuthError:
        raise HTTPException(422, {"error": "invalid_phone", "hint": "10-digit Indian mobile number"})
    q = db.query(Customer).filter(Customer.merchant_id == m.id, Customer.phone == phone)
    if exclude_id is not None:
        q = q.filter(Customer.id != exclude_id)
    other = q.first()
    if other:
        raise HTTPException(409, {"error": "phone_exists", "customer": other.name, "customer_id": other.id})
    return phone


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if any(ch in name for ch in "<>"):
        raise HTTPException(422, {"error": "invalid_name"})
    return name[:80]


def _row(c: Customer, bal: float, visits: int, last) -> dict:
    return {"id": c.id, "name": c.name, "phone": c.phone, "do_not_contact": c.do_not_contact, "created_at": c.created_at.isoformat(),
            "balance": round(bal, 2), "visits_90d": visits, "last_visit": last.isoformat() if last else None}


@router.get("/customers/all")
def customers_all(q: str = Query("", max_length=80), m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    """Every customer, newest first, with udhaar balance and recent visits. Optional search by name or number."""
    cs = db.query(Customer).filter_by(merchant_id=m.id)
    if q.strip():
        like = f"%{q.strip()}%"
        cs = cs.filter((Customer.name.ilike(like)) | (Customer.phone.like(f"%{''.join(ch for ch in q if ch.isdigit()) or '~'}%")))
    cs = cs.order_by(Customer.created_at.desc()).limit(500).all()
    since = clock.now() - timedelta(days=90)
    visits = dict(db.query(Transaction.customer_id, func.count(Transaction.id)).filter(
        Transaction.merchant_id == m.id, Transaction.ts >= since, Transaction.status == "success").group_by(Transaction.customer_id).all())
    last = dict(db.query(Transaction.customer_id, func.max(Transaction.ts)).filter(Transaction.merchant_id == m.id).group_by(Transaction.customer_id).all())
    bal = {r["customer_id"]: r["outstanding"] for r in ledger.dues(db, m)["customers"]}
    return {"customers": [_row(c, bal.get(c.id, 0.0), visits.get(c.id, 0), last.get(c.id)) for c in cs], "count": len(cs)}


@router.post("/customers", status_code=201)
def customer_add(body: CustomerIn, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    name = _clean_name(body.name)
    phone = _phone(db, m, body.phone)
    c = Customer(merchant_id=m.id, name=name, phone=phone, created_at=clock.now(), do_not_contact=body.do_not_contact)
    db.add(c)
    db.flush()
    audit.log(db, m.id, "merchant", "customer_added", {"customer_id": c.id})  # no name / number in the log
    db.commit()
    same = db.query(Customer).filter(Customer.merchant_id == m.id, Customer.id != c.id, func.lower(Customer.name) == name.lower()).count()
    return {**_row(c, 0.0, 0, None), "same_name_count": same}


@router.put("/customers/{customer_id}")
def customer_update(customer_id: int, body: CustomerPatch, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    c = db.query(Customer).filter_by(id=customer_id, merchant_id=m.id).first()
    if not c:
        raise HTTPException(404, {"error": "customer_not_found"})
    if body.name is not None:
        c.name = _clean_name(body.name)
    if body.phone is not None:
        c.phone = _phone(db, m, body.phone, exclude_id=c.id)
    if body.do_not_contact is not None:
        c.do_not_contact = body.do_not_contact
    audit.log(db, m.id, "merchant", "customer_updated", {"customer_id": c.id})
    db.commit()
    return _row(c, ledger.balance(db, m.id, c.id), 0, None)


@router.delete("/customers/{customer_id}")
def customer_delete(customer_id: int, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    """Remove a customer added by mistake. Someone with udhaar or payment history is kept (the books must add up);
    mark them 'do not contact' instead."""
    c = db.query(Customer).filter_by(id=customer_id, merchant_id=m.id).first()
    if not c:
        raise HTTPException(404, {"error": "customer_not_found"})
    if ledger.balance(db, m.id, c.id) > 0:
        raise HTTPException(409, {"error": "has_udhaar", "balance": ledger.balance(db, m.id, c.id)})
    has_history = db.query(LedgerEntry.id).filter_by(merchant_id=m.id, customer_id=c.id).first() or \
        db.query(Transaction.id).filter_by(merchant_id=m.id, customer_id=c.id).first()
    if has_history:
        raise HTTPException(409, {"error": "has_history"})
    db.delete(c)
    audit.log(db, m.id, "merchant", "customer_removed", {"customer_id": customer_id})
    briefing.invalidate(db, m.id)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- items (stock CRUD; create/list/delete live in account.py)

class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    unit: str | None = Field(default=None, min_length=1, max_length=12)
    price: float | None = Field(default=None, gt=0, le=1_000_000)
    gst_rate: Literal[0, 3, 5, 12, 18, 28] | None = None
    track_stock: bool | None = None
    pack_qty: float | None = Field(default=None, gt=0, le=100_000)
    supplier_id: int | None = None
    clear_supplier: bool = False
    stock_qty: float | None = Field(default=None, ge=0, le=1_000_000)  # a fresh count: sets the stock as of now


@router.put("/items/{item_id}")
def item_update(item_id: int, body: ItemPatch, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    it = db.query(Item).filter_by(id=item_id, merchant_id=m.id, active=True).first()
    if not it:
        raise HTTPException(404, {"error": "item_not_found"})
    if body.name is not None:
        name = " ".join(body.name.split())
        clash = db.query(Item).filter(Item.merchant_id == m.id, Item.active.is_(True), Item.id != it.id, Item.name.ilike(name)).first()
        if clash:
            raise HTTPException(409, {"error": "item_exists"})
        it.name = name
    if body.unit is not None:
        it.unit = body.unit.strip()
    if body.price is not None:
        it.price = body.price
    if body.gst_rate is not None:
        it.gst_rate = body.gst_rate
    if body.pack_qty is not None:
        it.pack_qty = body.pack_qty
    if body.clear_supplier:
        it.supplier_id = None
    elif body.supplier_id is not None:
        if not db.query(Supplier).filter_by(id=body.supplier_id, merchant_id=m.id).first():
            raise HTTPException(422, {"error": "unknown_supplier"})
        it.supplier_id = body.supplier_id
    if body.track_stock is not None:
        it.track_stock = body.track_stock
        if not body.track_stock:
            it.stock_qty, it.stock_reported_at = None, None
    if body.stock_qty is not None:
        if not it.track_stock:
            raise HTTPException(422, {"error": "stock_not_tracked"})
        it.stock_qty, it.stock_reported_at = body.stock_qty, clock.now()
    audit.log(db, m.id, "merchant", "item_updated", {"item_id": it.id, "fields": sorted(k for k, v in body.model_dump().items() if v not in (None, False))})
    briefing.invalidate(db, m.id)
    db.commit()
    return {"id": it.id, "name": it.name, "unit": it.unit, "price": it.price, "gst_rate": it.gst_rate, "track_stock": it.track_stock,
            "pack_qty": it.pack_qty, "supplier_id": it.supplier_id, "stock_qty": it.stock_qty}


# ---------------------------------------------------------------- approved messages: where they go

@router.get("/outbox")
def outbox(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return delivery.listing(db, m.id)


class MarkIn(BaseModel):
    status: Literal["sent", "ready", "skipped"] = "sent"


@router.post("/outbox/{outbox_id}/mark")
def outbox_mark(outbox_id: int, body: MarkIn | None = None, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    r = delivery.mark(db, m.id, outbox_id, (body.status if body else "sent"))
    if not r.get("ok"):
        raise HTTPException(404, r)
    return r
