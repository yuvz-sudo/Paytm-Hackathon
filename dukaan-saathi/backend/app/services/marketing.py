"""Marketing Studio. A campaign is drafted (template copy, optionally polished by one cheap LLM call), audience-selected,
capped by the merchant's discount guardrail, and only sent after approval. Performance is measured against a pre-send baseline."""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from .. import clock, config, messages
from ..models import Campaign, Customer, Merchant, Transaction
from ..util import inr
from . import actions, customers, retention

AUDIENCES = ("lapsed", "regulars", "all", "high_value", "repeat", "new", "at_risk")
MAX_RECIPIENTS = 100
POSTER_DIR = Path(__file__).resolve().parent.parent.parent / "posters"
POSTER_DAILY_LIMIT = 5


def _audience(db: Session, m: Merchant, audience: str) -> list[dict]:
    if audience in ("high_value", "repeat", "new", "at_risk"):
        return retention.audience(db, m, audience, MAX_RECIPIENTS)
    if audience == "all":
        rows = db.query(Customer).filter_by(merchant_id=m.id, do_not_contact=False).filter(Customer.phone != "").limit(MAX_RECIPIENTS).all()
        return [{"id": c.id, "name": c.name, "phone": c.phone} for c in rows]
    s = customers.summary(db, m)
    rows = s["lapsed"] if audience == "lapsed" else s["all_regulars"]
    if audience == "lapsed":
        return retention.audience(db, m, "lapsed", MAX_RECIPIENTS)
    return [{"id": r["customer_id"], "name": r["name"], "phone": r["phone"]} for r in rows if r["phone"] and not r["do_not_contact"]][:MAX_RECIPIENTS]


def _llm_message(db: Session, m: Merchant, occasion: str, pct: int, days: int) -> str | None:
    from ..agent import llm
    lang = {"en": "English", "hi": "Hindi (Devanagari)", "hinglish": "Hinglish (Roman script)"}.get(m.language, "English")
    prompt = (f"Write ONE WhatsApp message (max 2 short sentences, 1 emoji) from the small shop '{m.name}' ({m.segment}, {m.city}) to a regular customer "
              f"for the occasion '{occasion}'. Language: {lang}. Offer: {pct}% off, valid {days} days. Start with the greeting using the exact placeholder "
              "{name}. State the offer exactly as given; invent nothing else (no other prices, dates, links or products). Output only the message.")
    text = llm.write_copy(db, m.id, prompt)
    if not text or "{name}" not in text or len(text) > 400 or re.search(r"https?://|www\.", text):
        return None
    if pct and str(pct) not in text:
        return None  # the model drifted from the approved discount
    return text


def create(db: Session, m: Merchant, occasion: str, discount_pct: int = 10, valid_days: int = 7, audience: str = "lapsed",
           use_llm: bool = True) -> dict:
    occasion = (occasion or "").strip()[:60] or "special offer"
    if audience not in AUDIENCES:
        return {"ok": False, "error": "invalid_audience"}
    try:
        pct = int(discount_pct)
        days = max(1, min(int(valid_days), 30))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_discount"}
    if pct < 0:
        return {"ok": False, "error": "invalid_discount"}
    cap = min(m.max_offer_discount_pct, config.MAX_OFFER_DISCOUNT_PCT)
    clamped = pct > cap
    pct = min(pct, cap)
    recips = _audience(db, m, audience)
    if not recips:
        return {"ok": False, "error": "no_audience", "audience": audience}
    msg = _llm_message(db, m, occasion, pct, days) if use_llm else None
    source = "llm" if msg else "template"
    msg = msg or messages.campaign_message(m.language, m.name, occasion, pct, days)
    caption = re.sub(r"^\S*\s*\{name\}\s*(ji|जी)?[!,]?\s*", "", msg).strip() or msg  # message without the greeting, for posts
    c = Campaign(merchant_id=m.id, occasion=occasion, title=f"{occasion}: {pct}% off" if pct else occasion, caption=caption, message=msg,
                 discount_pct=pct, valid_days=days, audience=audience, recipients=recips, copy_source=source, created_at=clock.now())
    db.add(c)
    db.flush()
    a = actions.propose(db, m, "campaign_send", f"Send '{c.title}' to {len(recips)} customers",
                        {"campaign_id": c.id, "message": msg,
                         "recipients": [{"id": r["id"], "name": r["name"], "phone": r["phone"], "item": r.get("item"),
                                         "message": messages.with_item(m.language, msg, r.get("item")).replace("{name}", r["name"].split()[0])} for r in recips],
                         "discount_pct": pct}, dedupe_key=f"campaign:{c.id}")
    c.action_id = a["id"]
    db.commit()
    return {"ok": True, "campaign": view(db, m, c), "action": a, "discount_capped": clamped, "cap_pct": cap}


def _baseline(db: Session, m: Merchant, at: datetime) -> float:
    start = at - timedelta(days=14)
    rows = db.query(Transaction.amount).filter(Transaction.merchant_id == m.id, Transaction.status == "success",
                                               Transaction.ts >= start, Transaction.ts < at).all()
    return round(sum(a for (a,) in rows) / 14, 2)


def mark_sent(db: Session, m: Merchant, campaign_id: int) -> None:
    c = db.get(Campaign, campaign_id)
    if c and c.merchant_id == m.id and c.status == "draft":
        c.status, c.sent_at = "sent", clock.now()
        c.baseline_daily = _baseline(db, m, c.sent_at)


def performance(db: Session, m: Merchant, c: Campaign) -> dict | None:
    """Sales since sending vs the pre-send daily baseline, and how many recipients came back. Correlation, not proof."""
    if c.status != "sent" or not c.sent_at:
        return None
    now = clock.now()
    days = max((now - c.sent_at).total_seconds() / 86400, 0.0)
    rows = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.status == "success", Transaction.ts >= c.sent_at, Transaction.ts <= now).all()
    total = round(sum(t.amount for t in rows), 2)
    ids = {r["id"] for r in c.recipients}
    resp = [t for t in rows if t.customer_id in ids]
    expected = round(c.baseline_daily * days, 2)
    return {"days_since_sent": round(days, 1), "sales_since": total, "expected_without_campaign": expected,
            "lift": round(total - expected, 2),
            "lift_pct": round((total - expected) / expected * 100, 1) if expected and days >= 1 else None,  # no verdict in the first day
            "recipients": len(ids), "recipients_returned": len({t.customer_id for t in resp}), "recipient_revenue": round(sum(t.amount for t in resp), 2),
            "early": days < 3, "too_soon": days < 1, "note": "Compares sales after sending with your usual daily sales before it. Other things (festivals, weather) also move sales."}


def view(db: Session, m: Merchant, c: Campaign) -> dict:
    return {"id": c.id, "occasion": c.occasion, "title": c.title, "caption": c.caption, "message": c.message, "discount_pct": c.discount_pct,
            "valid_days": c.valid_days, "audience": c.audience, "recipient_count": len(c.recipients), "copy_source": c.copy_source, "status": c.status,
            "action_id": c.action_id, "created_at": c.created_at.isoformat(), "sent_at": c.sent_at.isoformat() if c.sent_at else None,
            "has_poster": bool(c.poster_path and Path(c.poster_path).exists()), "performance": performance(db, m, c)}


def list_all(db: Session, m: Merchant) -> dict:
    actions.expire_stale(db, m.id)
    rows = db.query(Campaign).filter_by(merchant_id=m.id).order_by(Campaign.id.desc()).limit(30).all()
    for c in rows:  # keep status in step with the approval it depends on
        if c.status in ("draft",) and c.action_id:
            from ..models import Action
            a = db.get(Action, c.action_id)
            if a and a.status in ("rejected", "expired", "failed"):
                c.status = a.status  # rejected | expired | failed
    db.commit()
    return {"campaigns": [view(db, m, c) for c in rows], "no_data": not rows}


def audiences(db: Session, m: Merchant) -> dict:
    return {a: len(_audience(db, m, a)) for a in AUDIENCES}


# ------------------------------------------------------------------ poster (Gemini)
def _poster_prompt(m: Merchant, c: Campaign) -> str:
    offer = f"{c.discount_pct}% OFF" if c.discount_pct else "Special offer"
    return (f"Design a vibrant, clean square promotional poster for a small Indian shop. Occasion: {c.occasion}. Shop name: '{m.name}' ({m.segment}, {m.city}). "
            f"Big readable headline text: '{offer}'. Small text: 'Valid {c.valid_days} days'. Warm festive colours suited to the occasion, no people's faces, "
            "no phone numbers, no logos of real brands. Spell the shop name and offer exactly.")


def poster(db: Session, m: Merchant, campaign_id: int, regenerate: bool = False) -> dict:
    c = db.get(Campaign, campaign_id)
    if not c or c.merchant_id != m.id:
        return {"ok": False, "error": "not_found"}
    if c.poster_path and Path(c.poster_path).exists() and not regenerate:
        return {"ok": True, "image": _data_url(Path(c.poster_path)), "cached": True}
    if not config.GEMINI_API_KEY:
        return {"ok": False, "error": "poster_not_configured"}
    from . import llm_budget
    if llm_budget.poster_count(db, m.id) >= POSTER_DAILY_LIMIT:
        return {"ok": False, "error": "poster_limit_reached", "limit": POSTER_DAILY_LIMIT}
    import httpx
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_IMAGE_MODEL}:generateContent",
                       headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}, timeout=90,
                       json={"contents": [{"parts": [{"text": _poster_prompt(m, c)}]}], "generationConfig": {"responseModalities": ["IMAGE"]}})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        b64 = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
    except Exception:
        return {"ok": False, "error": "poster_failed"}
    POSTER_DIR.mkdir(exist_ok=True)
    path = POSTER_DIR / f"m{m.id}_c{c.id}.png"
    path.write_bytes(base64.b64decode(b64))
    c.poster_path = str(path)
    llm_budget.record(db, m.id, "poster", 1, 0)
    return {"ok": True, "image": _data_url(path), "cached": False}


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
