"""Sign-up, login, onboarding and catalogue setup."""
from __future__ import annotations

from ..languages import SUPPORTED as SUPPORTED_LANGS

import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import clock
from ..db import get_db
from ..models import Consent, Item, Merchant, Supplier, Transaction
from ..seed import clear_merchant_data, populate, sample_spec_for
from ..services import audit, auth, briefing, consent
from .deps import bearer_token, current_merchant, session_merchant

router = APIRouter(prefix="/api")

LANGS = SUPPORTED_LANGS
SEGMENTS = ("kirana", "sweets", "salon", "pharmacy", "restaurant", "other")
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _auth_err(e: auth.AuthError):
    raise HTTPException(e.status, {"error": e.code})


class PhoneIn(BaseModel):
    phone: str = Field(max_length=20)


class VerifyIn(PhoneIn):
    otp: str = Field(max_length=6)


@router.post("/auth/request-otp")
def request_otp(body: PhoneIn, db: Session = Depends(get_db)):
    try:
        return auth.request_otp(db, body.phone)
    except auth.AuthError as e:
        _auth_err(e)


@router.post("/auth/verify")
def verify(body: VerifyIn, db: Session = Depends(get_db)):
    try:
        return auth.verify_otp(db, body.phone, body.otp)
    except auth.AuthError as e:
        _auth_err(e)


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    token = bearer_token(authorization)
    if token:
        auth.logout(db, token)
    return {"ok": True}


def _profile(m: Merchant) -> dict:
    return {"id": m.id, "name": m.name, "owner": m.owner_name, "segment": m.segment, "city": m.city, "language": m.language,
            "phone": m.phone, "gst_registered": m.gst_registered, "gst_number": m.gst_number, "soundbox_id": m.soundbox_id,
            "onboarded": m.onboarded, "sample_data": m.sample_data, "max_offer_discount_pct": m.max_offer_discount_pct}


@router.get("/auth/me")
def me(m: Merchant = Depends(session_merchant)):
    return _profile(m)


class OnboardIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    owner_name: str = Field(min_length=2, max_length=80)
    segment: Literal["kirana", "sweets", "salon", "pharmacy", "restaurant", "other"]
    city: str = Field(min_length=2, max_length=60)
    language: str
    gst_registered: bool = False
    gst_number: str | None = None
    soundbox_id: str | None = Field(default=None, max_length=30)
    consents: dict[str, bool]
    sample_data: bool = False

    @field_validator("business_name", "owner_name", "city")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", v).strip()
        if len(v) < 2 or re.search(r"[<>]", v):
            raise ValueError("invalid")
        return v

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGS:
            raise ValueError("unsupported_language")
        return v

    @field_validator("soundbox_id")
    @classmethod
    def _sb(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and not re.fullmatch(r"[A-Za-z0-9-]{4,30}", v):
            raise ValueError("invalid_soundbox_id")
        return v or None


@router.post("/onboarding")
def onboard(body: OnboardIn, m: Merchant = Depends(session_merchant), db: Session = Depends(get_db)):
    if m.onboarded:
        raise HTTPException(409, {"error": "already_onboarded"})
    unknown = set(body.consents) - set(consent.SCOPES) - {"reviews"}  # "reviews" was removed; older clients may still send it
    if unknown:
        raise HTTPException(422, {"error": "unknown_consent_scope", "scopes": sorted(unknown)})
    gst_no = (body.gst_number or "").strip().upper() or None
    if body.gst_registered and gst_no and not GSTIN.match(gst_no):
        raise HTTPException(422, {"error": "invalid_gstin"})
    m.name, m.owner_name, m.segment, m.city, m.language = body.business_name, body.owner_name, body.segment, body.city, body.language
    m.gst_registered, m.gst_number, m.soundbox_id = body.gst_registered, gst_no if body.gst_registered else None, body.soundbox_id
    now = clock.now()
    for scope in consent.SCOPES:  # explicit choice for every scope; anything not sent is OFF
        db.merge(Consent(merchant_id=m.id, scope=scope, granted=bool(body.consents.get(scope, False)), updated_at=now))
    m.onboarded = m.opted_in = True
    audit.log(db, m.id, "merchant", "onboarded", {"segment": body.segment, "language": body.language,
                                                  "consents": sorted(k for k, v in body.consents.items() if v)})
    if body.sample_data:
        populate(db, m, sample_spec_for(body.segment), now)
        m.sample_data = True
        audit.log(db, m.id, "system", "sample_data_loaded", {})
    db.commit()
    return _profile(m)


class ProfileIn(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=120)
    owner_name: str | None = Field(default=None, min_length=2, max_length=80)
    city: str | None = Field(default=None, min_length=2, max_length=60)
    gst_registered: bool | None = None
    gst_number: str | None = None
    max_offer_discount_pct: int | None = Field(default=None, ge=1, le=50)


@router.put("/merchant/profile")
def update_profile(body: ProfileIn, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    d = body.model_dump(exclude_unset=True)
    if "gst_number" in d and d["gst_number"]:
        d["gst_number"] = d["gst_number"].strip().upper()
        if not GSTIN.match(d["gst_number"]):
            raise HTTPException(422, {"error": "invalid_gstin"})
    mapping = {"business_name": "name", "owner_name": "owner_name", "city": "city", "gst_registered": "gst_registered",
               "gst_number": "gst_number", "max_offer_discount_pct": "max_offer_discount_pct"}
    for k, v in d.items():
        setattr(m, mapping[k], v)
    audit.log(db, m.id, "merchant", "profile_updated", {"fields": sorted(d)})
    briefing.invalidate(db, m.id)
    db.commit()
    return _profile(m)


@router.post("/onboarding/sample-data")
def load_sample(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    if db.query(Transaction.id).filter_by(merchant_id=m.id).first() or db.query(Item.id).filter_by(merchant_id=m.id).first():
        raise HTTPException(409, {"error": "merchant_already_has_data"})
    populate(db, m, sample_spec_for(m.segment), clock.now())
    m.sample_data = True
    audit.log(db, m.id, "system", "sample_data_loaded", {})
    briefing.invalidate(db, m.id)
    db.commit()
    return _profile(m)


@router.delete("/onboarding/sample-data")
def remove_sample(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    if not m.sample_data:
        raise HTTPException(409, {"error": "no_sample_data"})
    clear_merchant_data(db, m)
    audit.log(db, m.id, "merchant", "sample_data_removed", {})
    db.commit()
    return _profile(m)


# ---------------------------------------------------------------- catalogue
class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(max_length=20)
    lead_time_days: int = Field(default=2, ge=0, le=30)
    language: str = "hinglish"

    @field_validator("language")
    @classmethod
    def _l(cls, v: str) -> str:
        if v not in LANGS:
            raise ValueError("unsupported_language")
        return v


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    unit: str = Field(default="pc", min_length=1, max_length=12)
    price: float = Field(gt=0, le=1_000_000)
    gst_rate: Literal[0, 3, 5, 12, 18, 28] = 0
    track_stock: bool = True
    pack_qty: float = Field(default=1, gt=0, le=100_000)
    cover_days: int = Field(default=7, ge=1, le=60)
    supplier_id: int | None = None
    stock_qty: float | None = Field(default=None, ge=0, le=1_000_000)


@router.get("/suppliers")
def list_suppliers(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return [{"id": s.id, "name": s.name, "phone": s.phone, "lead_time_days": s.lead_time_days, "language": s.language}
            for s in db.query(Supplier).filter_by(merchant_id=m.id).order_by(Supplier.id)]


@router.post("/suppliers", status_code=201)
def add_supplier(body: SupplierIn, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    try:
        phone = auth.normalize_phone(body.phone)
    except auth.AuthError:
        raise HTTPException(422, {"error": "invalid_phone"})
    if db.query(Supplier).filter_by(merchant_id=m.id, name=body.name.strip()).first():
        raise HTTPException(409, {"error": "supplier_exists"})
    s = Supplier(merchant_id=m.id, name=body.name.strip(), phone=phone, lead_time_days=body.lead_time_days, language=body.language)
    db.add(s)
    audit.log(db, m.id, "merchant", "supplier_added", {"name": s.name})
    db.commit()
    return {"id": s.id, "name": s.name, "phone": s.phone, "lead_time_days": s.lead_time_days, "language": s.language}


@router.get("/items")
def list_items(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name, "unit": i.unit, "price": i.price, "gst_rate": i.gst_rate, "track_stock": i.track_stock,
             "supplier_id": i.supplier_id, "stock_qty": i.stock_qty, "aliases": i.aliases,
             "pack_qty": i.pack_qty, "cover_days": i.cover_days}
            for i in db.query(Item).filter_by(merchant_id=m.id, active=True).order_by(Item.name)]


@router.post("/items", status_code=201)
def add_item(body: ItemIn, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    name = body.name.strip()
    if db.query(Item).filter(Item.merchant_id == m.id, Item.active.is_(True)).filter(Item.name.ilike(name)).first():
        raise HTTPException(409, {"error": "item_exists"})
    if body.supplier_id is not None and not db.query(Supplier).filter_by(id=body.supplier_id, merchant_id=m.id).first():
        raise HTTPException(422, {"error": "unknown_supplier"})
    it = Item(merchant_id=m.id, name=name, aliases=[a.strip() for a in body.aliases if a.strip()], unit=body.unit.strip(),
              price=body.price, gst_rate=body.gst_rate, track_stock=body.track_stock, pack_qty=body.pack_qty,
              cover_days=body.cover_days, supplier_id=body.supplier_id,
              stock_qty=body.stock_qty if body.track_stock else None, stock_reported_at=clock.now() if body.stock_qty is not None and body.track_stock else None)
    db.add(it)
    audit.log(db, m.id, "merchant", "item_added", {"name": name})
    db.commit()
    return {"id": it.id, "name": it.name}


@router.delete("/items/{item_id}")
def remove_item(item_id: int, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    it = db.query(Item).filter_by(id=item_id, merchant_id=m.id, active=True).first()
    if not it:
        raise HTTPException(404, {"error": "item_not_found"})
    it.active = False  # soft delete: past sales still reference it
    audit.log(db, m.id, "merchant", "item_removed", {"name": it.name})
    db.commit()
    return {"ok": True}
