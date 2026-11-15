"""Conversation orchestrator.

Order of resolution: (1) confirmations for pending proposals -> deterministic, never delegated to an LLM;
(2) rule router for routine questions; (3) LLM planner for open-ended / multi-part questions;
(4) graceful fallback. Every turn is persisted so the dashboard and voice share one history."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import clock, config, i18n
from ..models import Action, ChatMessage, Merchant
from ..languages import NATIVE
from ..services import actions, llm_budget, sarvam
from . import llm, router, tools
from .tools import Ctx

log = logging.getLogger("dukaan.agent")
MAX_INPUT_CHARS = 1000


def _history(db: Session, mid: int, session_id: str, limit: int = 10) -> list[dict]:
    rows = db.query(ChatMessage).filter_by(merchant_id=mid, session_id=session_id).order_by(ChatMessage.id.desc()).limit(limit).all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def _awaiting(db: Session, mid: int, session_id: str) -> list[int]:
    """Action ids from the latest assistant turn that still await a decision."""
    last = (db.query(ChatMessage).filter_by(merchant_id=mid, session_id=session_id, role="assistant")
            .order_by(ChatMessage.id.desc()).first())
    ids = (last.meta or {}).get("action_ids", []) if last else []
    if not ids:
        return []
    actions.expire_stale(db, mid)
    return [a.id for a in db.query(Action).filter(Action.id.in_(ids), Action.merchant_id == mid, Action.status == "pending")]


def _decide(ctx: Ctx, ids: list[int], approve: bool, lang: str) -> str:
    ok, bad = [], []
    for aid in ids:
        r = actions.approve(ctx.db, ctx.merchant.id, aid) if approve else actions.reject(ctx.db, ctx.merchant.id, aid)
        ctx.trace.append({"tool": "decide_action", "args": {"action_id": aid, "decision": "approve" if approve else "reject"}, "ok": r.get("ok", False)})
        (ok if r.get("ok") else bad).append((aid, r))
    L = router.L
    if not approve:
        return L(lang, "Okay, I won't send it.", "ठीक है, नहीं भेजूँगा।", "Theek hai, nahi bhejunga.")
    if ok and not bad:
        n = len(ok)
        return L(lang, f"Approved ({n}). Open Approvals → Ready to send and tap “Open in WhatsApp” to send it from your number.",
                 f"मंज़ूर ({n})। मंज़ूरी → भेजने के लिए तैयार में “Open in WhatsApp” दबाकर अपने नंबर से भेजें।",
                 f"Approve ho gaya ({n}). Approvals → Ready to send mein “Open in WhatsApp” dabakar apne number se bhejiye.")
    reasons = ", ".join(sorted({(r.get("summary") or r.get("error") or "failed") for _, r in bad}))
    if ok:
        return L(lang, f"{len(ok)} done, but {len(bad)} could not be completed ({reasons}).", f"{len(ok)} हुए, {len(bad)} नहीं हो पाए ({reasons})।",
                 f"{len(ok)} ho gaye, {len(bad)} nahi ho paaye ({reasons}).")
    return L(lang, f"I couldn't complete that: {reasons}.", f"यह पूरा नहीं हो पाया: {reasons}।", f"Yeh poora nahi ho paaya: {reasons}.")


READ_INTENTS = {"sales", "best", "hours", "stock", "dues", "settlements", "gst", "credit", "customers", "festivals", "briefing",
                "explain", "advice", "item_info", "customer_balance", "close_day"}
FOLLOW_UP = {"sales", "best", "gst", "explain"}
SPLIT = re.compile(r"\s*(?:,|;|\band\b|\baur\b|\bphir\b|\bthen\b|\balso\b|\bऔर\b|\bफिर\b)\s*", re.I)


def _last_meta(db: Session, mid: int, session_id: str) -> dict:
    last = (db.query(ChatMessage).filter_by(merchant_id=mid, session_id=session_id, role="assistant").order_by(ChatMessage.id.desc()).first())
    return (last.meta or {}) if last else {}


def _route(ctx: Ctx, text: str, awaiting: list[int], prev: dict) -> tuple[str, dict]:
    """Rule routing with item awareness and follow-up memory ("and last week?")."""
    intent, ent = router.classify(text, has_pending=bool(awaiting))
    if intent in ("stock", "sales", "best", "unknown"):
        item = router.item_in_text(ctx, text)
        if item and not re.search(r"\b(order|mangwa|supplier)\b", text.lower()):
            return "item_info", {"item": item}
    if intent == "unknown" and prev.get("intent") in FOLLOW_UP:
        per = router.explicit_period(router.norm(text))
        if per and len(text.split()) <= 6:  # "aur kal?", "and last week?"
            return prev["intent"], {**prev.get("ent", {}), "period": per}
    return intent, ent


def _compound(ctx: Ctx, text: str, awaiting: list[int], prev: dict) -> list[tuple[str, dict]] | None:
    parts = [p for p in SPLIT.split(text) if len(p.strip()) >= 2]
    if not (2 <= len(parts) <= 3):
        return None
    routed = [_route(ctx, p, awaiting, prev) for p in parts]
    if all(i in READ_INTENTS for i, _ in routed) and len({i for i, _ in routed}) == len(routed):
        return routed
    return None


def purge_old(db: Session, merchant_id: int) -> None:
    """Chats are kept for CHAT_RETENTION_DAYS, then deleted."""
    cutoff = clock.now() - timedelta(days=config.CHAT_RETENTION_DAYS)
    db.query(ChatMessage).filter(ChatMessage.merchant_id == merchant_id, ChatMessage.ts < cutoff).delete(synchronize_session=False)
    db.commit()


def recent(db: Session, merchant: Merchant, limit: int = 120) -> dict:
    """The latest conversation from the retention window, with approval cards that are still pending."""
    purge_old(db, merchant.id)
    last = db.query(ChatMessage).filter_by(merchant_id=merchant.id).order_by(ChatMessage.id.desc()).first()
    if not last:
        return {"session_id": None, "messages": [], "retention_days": config.CHAT_RETENTION_DAYS}
    rows = (db.query(ChatMessage).filter_by(merchant_id=merchant.id, session_id=last.session_id)
            .order_by(ChatMessage.id.desc()).limit(limit).all())[::-1]
    actions.expire_stale(db, merchant.id)
    pending = {a["id"]: a for a in actions.list_actions(db, merchant.id, "pending")}
    msgs = []
    for r in rows:
        meta = r.meta or {}
        msgs.append({"role": r.role, "text": r.content, "ts": r.ts.isoformat(), "lang": meta.get("language"),
                     "actions": [pending[i] for i in meta.get("action_ids", []) if i in pending]})
    return {"session_id": last.session_id, "messages": msgs, "retention_days": config.CHAT_RETENTION_DAYS,
            "expires_at": (rows[0].ts + timedelta(days=config.CHAT_RETENTION_DAYS)).isoformat() if rows else None}


def handle_message(db: Session, merchant: Merchant, text: str, session_id: str | None = None, language: str | None = None) -> dict:
    session_id = session_id or uuid.uuid4().hex[:16]
    purge_old(db, merchant.id)
    text = (text or "").strip()[:MAX_INPUT_CHARS]
    lang = router.detect_language(text, language or merchant.language)
    ctx = Ctx(db=db, merchant=merchant, last_user_message=text)
    engine = "rules"
    prev = _last_meta(db, merchant.id, session_id)

    db.add(ChatMessage(merchant_id=merchant.id, session_id=session_id, role="user", content=text, ts=clock.now()))
    db.commit()

    awaiting = _awaiting(db, merchant.id, session_id)
    intent, ent = _route(ctx, text, awaiting, prev)
    reply = ""
    err_msg = router.L(lang, "Sorry, I'm having trouble right now. Please try again in a moment.", "क्षमा करें, अभी कुछ दिक्कत है। थोड़ी देर बाद कोशिश करें।",
                       "Maaf kijiye, abhi kuch dikkat hai. Thodi der baad try kijiye.")

    def by_rules() -> str:
        compound = _compound(ctx, text, awaiting, prev)
        if compound:
            return "\n".join(router.handle(ctx, i, e, lang) for i, e in compound)
        return router.handle(ctx, intent, ent, lang)

    try:
        if intent in ("confirm_yes", "confirm_no"):
            reply = _decide(ctx, awaiting, intent == "confirm_yes", lang)  # money/messages never go through an LLM
        elif intent == "empty":
            reply = router.handle(ctx, "empty", {}, lang)
        elif llm.available() and llm_budget.allowed(db, merchant.id, 1) and not (
                config.LLM_MODE == "rules_first" and intent != "unknown" and intent not in ("advice", "explain")):
            # With an LLM the planner answers everything (follow-ups, multi-part, "why", advice); rules are the safety net.
            engine = "llm"
            try:
                reply = llm.chat(ctx, _history(db, merchant.id, session_id, config.LLM_HISTORY_TURNS)[:-1], text)
            except Exception as e:  # network / quota: degrade to rules instead of failing
                log.warning("LLM unavailable, falling back to rules: %s", e)
                db.rollback()
                engine, reply = "rules", ""
            if not reply:
                engine, reply = "rules", by_rules()
        else:
            reply = by_rules()
    except Exception as e:  # never surface a stack trace to a merchant
        log.exception("agent failure: %s", e)
        db.rollback()
        engine, reply = "error", err_msg

    pending_ids = [i for i in ctx.proposed_action_ids]
    meta = {"action_ids": pending_ids, "intent": intent, "ent": {k: v for k, v in ent.items() if k in ("period", "item")}, "language": lang}
    db.add(ChatMessage(merchant_id=merchant.id, session_id=session_id, role="assistant", content=reply, ts=clock.now(), meta=meta))
    db.commit()
    return {"session_id": session_id, "reply": reply, "language": lang, "engine": engine, "intent": intent,
            "tools": ctx.trace, "pending_actions": [a for a in actions.list_actions(db, merchant.id, "pending") if a["id"] in pending_ids]}


def respond(db: Session, merchant: Merchant, text: str, session_id: str | None = None, language: str | None = None) -> dict:
    """Entry point for chat and voice in any supported language.
    en / hi / hinglish are answered directly. Other Indian languages go through Sarvam: the merchant's words are
    translated to English, answered by the same rules/LLM (so approvals and safety rules are identical), and the answer
    is translated back. If translation is down the merchant still gets an answer, in English."""
    lang = language or merchant.language
    if lang not in NATIVE:
        return handle_message(db, merchant, text, session_id, language)
    english = sarvam.to_english(text, lang, merchant.id)
    out = handle_message(db, merchant, english, session_id, "en")
    out["understood_as"] = english if english != (text or "").strip() else None
    try:
        out["reply"] = sarvam.translate(db, out["reply"], lang, merchant_id=merchant.id)
        out["language"] = lang
    except Exception as e:  # never lose the answer because translation failed
        log.warning("reply translation failed: %s", e)
        db.rollback()
        out["language"] = "en"
    _store_as_seen(db, merchant.id, out["session_id"], (text or "").strip(), english, out["reply"], out["language"])
    return out


def _store_as_seen(db: Session, mid: int, session_id: str, original: str, english: str, reply: str, lang: str) -> None:
    """The saved chat should show the merchant's own words and the reply in their language (not our English working copy)."""
    try:
        rows = (db.query(ChatMessage).filter_by(merchant_id=mid, session_id=session_id).order_by(ChatMessage.id.desc()).limit(2).all())
        for r in rows:
            if r.role == "assistant":
                r.content, r.meta = reply, {**(r.meta or {}), "language": lang}
            elif r.role == "user" and original:
                r.content, r.meta = original[:MAX_INPUT_CHARS], {**(r.meta or {}), "english": english}
        db.commit()
    except Exception as e:
        log.warning("could not store translated chat: %s", e)
        db.rollback()
