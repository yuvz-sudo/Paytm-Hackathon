from __future__ import annotations

from ..languages import SUPPORTED as SUPPORTED_LANGS

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import clock, config
from ..agent import agent as agent_mod
from ..db import get_db
from .deps import current_merchant, need
from ..models import ChatMessage, Merchant, Outbox
from ..services import (actions, analytics, audit, briefing, consent, credit, customers, fees, growth, gst, inventory, ledger, payments,
                        procurement, settlements)
from ..services import advisor, finance, llm_budget, marketing, news, retention

router = APIRouter(prefix="/api")

LANGS = SUPPORTED_LANGS


Amount = Field(gt=0, le=10_000_000)


class UdhaarIn(BaseModel):
    customer: str = Field(default="", max_length=80)
    customer_id: int | None = None  # from a row button: exact, never ambiguous
    amount: float = Amount
    note: str = Field(default="", max_length=200)
    create_if_missing: bool = False


class PaymentIn(BaseModel):
    customer: str = Field(default="", max_length=80)
    customer_id: int | None = None
    amount: float = Amount


class RemindIn(BaseModel):
    customer: str | None = Field(default=None, max_length=80)
    customer_id: int | None = None


class StockIn(BaseModel):
    item: str = Field(min_length=1, max_length=80)
    quantity: float = Field(ge=0, le=1_000_000)
    mode: Literal["set", "add"] = "set"


class OrderIn(BaseModel):
    items: list[str] | None = None


class WinbackIn(BaseModel):
    discount_pct: int = Field(default=10, ge=1, le=100)
    valid_days: int = Field(default=7, ge=1, le=30)
    send_hour: int | None = Field(default=None, ge=0, le=23)  # steer the offer into this hour; default = next quiet hour


class CampaignIn(BaseModel):
    occasion: str = Field(min_length=1, max_length=60)
    discount_pct: int = Field(default=10, ge=0, le=100)
    valid_days: int = Field(default=7, ge=1, le=30)
    audience: Literal["lapsed", "regulars", "all", "high_value", "repeat", "new", "at_risk"] = "lapsed"
    use_llm: bool = True


class SegmentOfferIn(BaseModel):
    segment: Literal["high_value", "repeat", "new", "at_risk", "lapsed"]
    discount_pct: int | None = Field(default=None, ge=0, le=100)
    use_llm: bool = True


class PosterIn(BaseModel):
    regenerate: bool = False


class ProofIn(BaseModel):
    chargeback_id: int | None = None


class ApproveIn(BaseModel):
    edited_message: str | None = Field(default=None, max_length=1000)


class ConsentIn(BaseModel):
    granted: bool


class ChatIn(BaseModel):
    message: str = Field(max_length=2000)
    session_id: str | None = Field(default=None, max_length=40)
    language: str | None = None


class LangIn(BaseModel):
    language: str


def _fail(res: dict, status: int = 400) -> dict:
    if res.get("ok") is False or res.get("error"):
        code = 404 if res.get("error") in ("customer_not_found", "item_not_found", "not_found") else 409 if res.get("error") in (
            "ambiguous_customer", "ambiguous_item") else status
        raise HTTPException(code, res)
    return res


@router.get("/health")
def health():
    from ..agent import llm
    return {"ok": True, "llm": llm.available(), "now": clock.now().isoformat()}


@router.get("/llm/usage")
def llm_usage(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return llm_budget.summary(db, m.id)


@router.get("/merchants")
def merchants(db: Session = Depends(get_db)):
    if not config.ALLOW_DEMO_HEADER:
        raise HTTPException(404, "not_found")
    return [{"id": m.id, "name": m.name, "owner": m.owner_name, "segment": m.segment, "city": m.city, "language": m.language}
            for m in db.query(Merchant).order_by(Merchant.id)]


@router.get("/merchant")
def merchant(m: Merchant = Depends(current_merchant)):
    return {"id": m.id, "name": m.name, "owner": m.owner_name, "segment": m.segment, "city": m.city, "language": m.language,
            "gst_registered": m.gst_registered, "soundbox_id": m.soundbox_id, "max_offer_discount_pct": m.max_offer_discount_pct}


@router.put("/merchant/language")
def set_language(body: LangIn, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    if body.language not in LANGS:
        raise HTTPException(422, {"error": "unsupported_language", "supported": sorted(LANGS)})
    m.language = body.language
    audit.log(db, m.id, "merchant", "language_changed", {"language": body.language})
    briefing.invalidate(db, m.id)  # cached briefing was written in the old language
    db.commit()
    return {"ok": True, "language": m.language}


@router.get("/briefing")
def get_briefing(refresh: bool = False, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return briefing.get_or_create(db, m, refresh)


@router.get("/sales/summary")
def sales_summary(period: str = "yesterday", m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return analytics.sales_summary(db, m, period)


@router.get("/sales/series")
def sales_series(days: int = Query(30, ge=1, le=90), m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return analytics.daily_series(db, m, days)


@router.get("/sales/best")
def best(period: str = "last_7_days", limit: int = Query(5, ge=1, le=20), m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return analytics.best_sellers(db, m, period, limit)


@router.get("/sales/compare")
def sales_compare(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return growth.compare(db, m)


@router.get("/growth/advisor")
def growth_advisor(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return growth.advisor(db, m)


@router.get("/growth/plan")
def growth_plan(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    """Seasonal stock moves, slow sellers to discount, money advice and price news, plus the advisor's note."""
    p = advisor.plan(db, m)
    p["note"] = advisor.note(db, m, p)
    return p


@router.post("/growth/note")
def growth_note(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    """Rewrite today's note (still at most one paid LLM note per day)."""
    return advisor.note(db, m, advisor.plan(db, m), refresh=True)


@router.get("/news")
def market_news(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    """Real headlines for this kind of business (no merchant data leaves the app: only the business type is searched)."""
    return news.for_merchant(db, m)


@router.get("/sales/hours")
def hours(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return {**analytics.hourly_profile(db, m), "weekdays": analytics.weekday_profile(db, m)}


@router.get("/stock")
def stock(only_risky: bool = False, m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return inventory.stock_status(db, m, only_risky)


@router.post("/stock/update")
def stock_update(body: StockIn, m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    r = _fail(inventory.update_stock(db, m, body.item, body.quantity, body.mode))
    audit.log(db, m.id, "merchant", "stock_updated", {"item": r["item"], "stock": r["stock"]})
    db.commit()
    return r


@router.post("/stock/order")
def stock_order(body: OrderIn, m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return _fail(procurement.propose_supplier_orders(db, m, body.items))


@router.get("/udhaar")
def udhaar(m: Merchant = Depends(need("ledger")), db: Session = Depends(get_db)):
    return ledger.dues(db, m)


@router.post("/udhaar/credit")
def udhaar_credit(body: UdhaarIn, m: Merchant = Depends(need("ledger")), db: Session = Depends(get_db)):
    if not body.customer.strip() and body.customer_id is None:
        raise HTTPException(422, {"error": "customer_required"})
    return _fail(ledger.add_credit(db, m, body.customer, body.amount, body.note, create_if_missing=body.create_if_missing, customer_id=body.customer_id))


@router.post("/udhaar/payment")
def udhaar_payment(body: PaymentIn, m: Merchant = Depends(need("ledger")), db: Session = Depends(get_db)):
    if not body.customer.strip() and body.customer_id is None:
        raise HTTPException(422, {"error": "customer_required"})
    return _fail(ledger.record_payment(db, m, body.customer, body.amount, customer_id=body.customer_id))


@router.post("/udhaar/remind")
def udhaar_remind(body: RemindIn, m: Merchant = Depends(need("ledger")), db: Session = Depends(get_db)):
    return _fail(ledger.propose_reminders(db, m, body.customer, customer_id=body.customer_id))


@router.get("/customers")
def customers_summary(m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    return customers.summary(db, m)


@router.post("/customers/winback")
def customers_winback(body: WinbackIn, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    return _fail(customers.propose_winback(db, m, body.discount_pct, body.valid_days, send_hour=body.send_hour))


@router.get("/marketing/campaigns")
def campaigns_list(m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    return {**marketing.list_all(db, m), "audiences": marketing.audiences(db, m)}


@router.post("/marketing/campaigns")
def campaigns_create(body: CampaignIn, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    return _fail(marketing.create(db, m, body.occasion, body.discount_pct, body.valid_days, body.audience, body.use_llm))


@router.post("/marketing/campaigns/{campaign_id}/poster")
def campaign_poster(campaign_id: int, body: PosterIn | None = None, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    r = marketing.poster(db, m, campaign_id, body.regenerate if body else False)
    db.commit()
    if r.get("error") == "poster_limit_reached":
        raise HTTPException(429, r)
    if r.get("error") in ("poster_failed", "poster_not_configured"):
        raise HTTPException(502, r)
    return _fail(r)


@router.get("/retention/segments")
def retention_segments(m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    return retention.segments(db, m)


@router.post("/retention/offers")
def retention_offer(body: SegmentOfferIn, m: Merchant = Depends(need("customers")), db: Session = Depends(get_db)):
    d = retention.OFFER[body.segment]
    pct = d["pct"] if body.discount_pct is None else body.discount_pct
    return _fail(marketing.create(db, m, d["occasion"], pct, 7, body.segment, body.use_llm))


@router.get("/finance/report")
def finance_report(period: str = "this_month", m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return finance.report(db, m, period)


@router.get("/finance/forecast")
def finance_forecast(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return finance.forecast(db, m)


@router.get("/gst")
def gst_summary(period: str = "last_month", m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return gst.summary(db, m, period)


@router.get("/settlements")
def settlements_status(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return settlements.status(db, m)


@router.get("/settlements/{settlement_id}/explain")
def settlement_explain(settlement_id: int, m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return _fail(settlements.explain(db, m, settlement_id))


@router.get("/chargebacks")
def chargebacks_list(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return settlements.chargebacks(db, m)


@router.post("/chargebacks/proof")
def chargeback_proof(body: ProofIn | None = None, m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    r = settlements.propose_proof(db, m, body.chargeback_id if body else None)
    if r.get("error") in ("chargeback_not_open", "deadline_passed"):
        raise HTTPException(409, r)
    return _fail(r)


@router.get("/fees/mdr")
def fees_mdr(period: str = "this_month", m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return fees.mdr_estimate(db, m, period)


@router.get("/transactions/today")
def transactions_today(m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return payments.today(db, m)


@router.get("/transactions")
def transactions_for_day(day: Literal["today", "yesterday"] = "today", m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return payments.today(db, m, day)


@router.get("/payments/verify")
def payments_verify(amount: float = Query(gt=0, le=10_000_000), minutes: int = Query(5, ge=1, le=120),
                    m: Merchant = Depends(need("transactions")), db: Session = Depends(get_db)):
    return payments.verify(db, m, amount, minutes)


@router.get("/credit")
def credit_suggestion(m: Merchant = Depends(need("credit")), db: Session = Depends(get_db)):
    return credit.suggestion(db, m)


@router.get("/actions")
def list_actions(status: str | None = "pending", m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return actions.list_actions(db, m.id, None if status == "all" else status)


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: int, body: ApproveIn | None = None, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    r = actions.approve(db, m.id, action_id, body.edited_message if body else None)
    if r.get("error") == "not_found":
        raise HTTPException(404, r)
    if r.get("conflict"):
        raise HTTPException(409, r)
    return r


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: int, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    r = actions.reject(db, m.id, action_id)
    if r.get("error") == "not_found":
        raise HTTPException(404, r)
    if r.get("conflict"):
        raise HTTPException(409, r)
    return r


@router.get("/consent")
def get_consent(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return consent.all_for(db, m.id)


@router.put("/consent/{scope}")
def put_consent(scope: str, body: ConsentIn, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    try:
        consent.set_scope(db, m.id, scope, body.granted)
    except ValueError:
        raise HTTPException(404, {"error": "unknown_scope"})
    return consent.all_for(db, m.id)


@router.get("/audit")
def get_audit(limit: int = Query(50, ge=1, le=200), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return audit.recent(db, m.id, limit)


@router.post("/chat")
def chat(body: ChatIn, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    if body.language and body.language not in LANGS:
        raise HTTPException(422, {"error": "unsupported_language"})
    return agent_mod.respond(db, m, body.message, body.session_id, body.language)


@router.get("/chat/recent")
def chat_recent(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    """Latest Ask Saathi conversation from the last CHAT_RETENTION_DAYS (7) days, so it survives reloads and devices."""
    return agent_mod.recent(db, m)


@router.get("/chat/history")
def chat_history(session_id: str = Query(max_length=40), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    rows = db.query(ChatMessage).filter_by(merchant_id=m.id, session_id=session_id).order_by(ChatMessage.id).limit(200).all()
    return [{"role": r.role, "content": r.content, "ts": r.ts.isoformat()} for r in rows]
