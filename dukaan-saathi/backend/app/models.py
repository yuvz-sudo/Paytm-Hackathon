from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_name: Mapped[str] = mapped_column(String(80))
    segment: Mapped[str] = mapped_column(String(30))  # kirana | sweets | salon | pharmacy
    city: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(10), default="hinglish")  # en | hi | hinglish | mr | ta ...
    phone: Mapped[str] = mapped_column(String(20), default="", index=True)
    gst_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_in: Mapped[bool] = mapped_column(Boolean, default=True)
    soundbox_id: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    max_offer_discount_pct: Mapped[int] = mapped_column(Integer, default=15)
    gst_number: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)  # false until the sign-up wizard is finished
    sample_data: Mapped[bool] = mapped_column(Boolean, default=False)  # true when payments are simulated demo data
    quiet_start_hour: Mapped[int] = mapped_column(Integer, default=22)  # no proactive pings 22:00-07:00
    quiet_end_hour: Mapped[int] = mapped_column(Integer, default=7)


class Consent(Base):
    __tablename__ = "consents"
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(30), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20), default="")
    lead_time_days: Mapped[int] = mapped_column(Integer, default=2)
    language: Mapped[str] = mapped_column(String(10), default="hinglish")


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    unit: Mapped[str] = mapped_column(String(12), default="pc")
    price: Mapped[float] = mapped_column(Float)
    gst_rate: Mapped[float] = mapped_column(Float, default=0.0)
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    stock_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # as last reported by merchant
    stock_reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pack_qty: Mapped[float] = mapped_column(Float, default=1.0)  # supplier's typical order multiple
    cover_days: Mapped[int] = mapped_column(Integer, default=7)  # how many days of sales one order should cover (short for perishables)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    amount: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(10), default="UPI")  # UPI | CARD | WALLET
    status: Mapped[str] = mapped_column(String(10), default="success")  # success | failed | refunded
    itemized: Mapped[bool] = mapped_column(Boolean, default=False)
    items: Mapped[list["TxnItem"]] = relationship(back_populates="txn", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_txn_merchant_ts", "merchant_id", "ts"),)


class TxnItem(Base):
    __tablename__ = "txn_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    txn_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    qty: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    txn: Mapped[Transaction] = relationship(back_populates="items")


class LedgerEntry(Base):
    """Udhaar book. kind = credit_given (customer owes more) | payment_received."""
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="google")
    author: Mapped[str] = mapped_column(String(60), default="")
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    ts: Mapped[datetime] = mapped_column(DateTime)
    replied: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    expected_date: Mapped[date] = mapped_column(Date)
    settled_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="settled")  # settled | pending | failed
    utr: Mapped[str] = mapped_column(String(30), default="")
    failure_reason: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


class SettlementLine(Base):
    """One deduction on a settlement. kind: commission | gst | rental | refund | chargeback | recovery.
    Invariant: Settlement.amount (net) = gross - sum(lines)."""
    __tablename__ = "settlement_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    settlement_id: Mapped[int] = mapped_column(ForeignKey("settlements.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Float)  # positive = amount deducted


class Chargeback(Base):
    __tablename__ = "chargebacks"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    txn_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    raised_date: Mapped[date] = mapped_column(Date)
    proof_due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | proof_sent | lost | won
    reason: Mapped[str] = mapped_column(String(160), default="")


class Payable(Base):
    """Money the merchant owes suppliers; used for cash-flow gap detection."""
    __tablename__ = "payables"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    due_date: Mapped[date] = mapped_column(Date)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(120), default="")


class Action(Base):
    """Anything Dukaan Saathi wants to do on the merchant's behalf. Nothing runs until approved."""
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # supplier_order | udhaar_reminder | winback_offer | review_reply
    title: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|executed|rejected|expired|failed
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Outbox(Base):
    """Messages that left the system after approval (WhatsApp/SMS stub)."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    action_id: Mapped[Optional[int]] = mapped_column(ForeignKey("actions.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(12), default="whatsapp")
    to_name: Mapped[str] = mapped_column(String(80))
    to_phone: Mapped[str] = mapped_column(String(20), default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    actor: Mapped[str] = mapped_column(String(20))  # merchant | agent | system
    event: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # e.g. {"action_ids": [..]} awaiting confirmation


class Briefing(Base):
    __tablename__ = "briefings"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    for_date: Mapped[date] = mapped_column(Date)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class OtpChallenge(Base):
    """One-time passcode for phone login. Only a salted hash is stored."""
    __tablename__ = "otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    salt: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthSession(Base):
    """Bearer session. The token itself is never stored, only its SHA-256."""
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class LlmUsage(Base):
    """Per merchant per day count of LLM requests and tokens, so credits cannot run away."""
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="chat")  # chat | campaign | poster
    requests: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)


class Campaign(Base):
    """A marketing campaign draft. Nothing is sent until the linked Action is approved."""
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    occasion: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(160))
    caption: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text)  # WhatsApp text; {name} is personalised per recipient
    discount_pct: Mapped[int] = mapped_column(Integer, default=0)
    valid_days: Mapped[int] = mapped_column(Integer, default=7)
    audience: Mapped[str] = mapped_column(String(20), default="lapsed")  # lapsed | regulars | all
    recipients: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    copy_source: Mapped[str] = mapped_column(String(12), default="template")  # template | llm
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | sent | rejected | expired
    action_id: Mapped[Optional[int]] = mapped_column(ForeignKey("actions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    baseline_daily: Mapped[float] = mapped_column(Float, default=0.0)  # average daily sales in the 14 days before sending
    poster_path: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class TranslationCache(Base):
    """Sarvam translations, so each UI string / reply is paid for once per language."""
    __tablename__ = "translation_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    src_lang: Mapped[str] = mapped_column(String(10))
    tgt_lang: Mapped[str] = mapped_column(String(10))
    src_hash: Mapped[str] = mapped_column(String(40))
    src: Mapped[str] = mapped_column(Text)
    out: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (Index("ux_translation", "tgt_lang", "src_lang", "src_hash", unique=True),)


class AdvisorNote(Base):
    """The Growth Advisor's daily note (LLM-written at most once a day per language, else a template)."""
    __tablename__ = "advisor_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    for_date: Mapped[date] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))  # llm | template
    created_at: Mapped[datetime] = mapped_column(DateTime)


class DeliveryStatus(Base):
    """Whether an approved message has actually been sent by the merchant (from their own WhatsApp / SMS)."""
    __tablename__ = "delivery_status"
    outbox_id: Mapped[int] = mapped_column(ForeignKey("outbox.id"), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="ready")  # ready | sent | skipped
    updated_at: Mapped[datetime] = mapped_column(DateTime)
