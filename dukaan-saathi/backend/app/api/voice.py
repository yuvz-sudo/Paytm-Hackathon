"""Languages, UI translation and voice (Sarvam AI).

Every endpoint degrades cleanly: if Sarvam is missing or down, translation returns the original text and the voice
endpoints answer 503 {"error": "voice_unavailable"} so the browser can fall back to its own speech engine."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agent import agent as agent_mod
from ..agent.navigate import INTENT_TAB, nav_target
from ..db import get_db
from ..languages import LANGUAGES, NATIVE, SUPPORTED, from_sarvam, listing
from ..models import Merchant
from ..services import sarvam
from .deps import current_merchant, session_merchant

router = APIRouter(prefix="/api")
log = logging.getLogger("dukaan.voice")
MAX_AUDIO = sarvam.STT_MAX_BYTES


def _lang(lang: str | None, m: Merchant) -> str:
    lang = lang or m.language or "en"
    if lang not in SUPPORTED:
        raise HTTPException(422, {"error": "unsupported_language", "supported": sorted(SUPPORTED)})
    return lang


async def audio_body(request: Request) -> bytes:
    """Raw audio upload (WAV preferred; WebM/MP4/OGG accepted). Read with a hard size cap."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_AUDIO:
            raise HTTPException(413, {"error": "audio_too_long", "max_seconds": 30})
    if len(data) < 1000:
        raise HTTPException(422, {"error": "audio_too_short"})
    return bytes(data)


def _unavailable(e: Exception):
    reason = str(e) or "error"
    log.info("voice unavailable: %s", reason)
    raise HTTPException(503, {"error": "voice_unavailable", "reason": reason})


@router.get("/languages")
def languages():
    return {"languages": listing(), "voice": sarvam.available(), "translation": sarvam.available()}


class TranslateIn(BaseModel):
    language: str
    texts: list[str] = Field(max_length=80)


@router.post("/i18n/translate")
def translate_ui(body: TranslateIn, m: Merchant = Depends(session_merchant), db: Session = Depends(get_db)):
    """UI strings for the dashboard (session_merchant: also works during onboarding)."""
    lang = _lang(body.language, m)
    texts = [t[:400] for t in body.texts]
    if lang in ("en", "hinglish"):
        return {"language": lang, "translations": texts, "retry": []}
    try:
        out, failed = sarvam.translate_status(db, texts, lang, merchant_id=m.id, interactive=False)
    except Exception as e:  # cache / network trouble: show English rather than fail the page
        log.warning("ui translation failed: %s", e)
        db.rollback()
        out, failed = texts, list(range(len(texts)))
    # failed: not translated *yet* (Sarvam busy); the page asks again in a few seconds
    return {"language": lang, "translations": out, "retry": failed}


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    language: str | None = None


@router.post("/voice/tts")
def voice_tts(body: TtsIn, m: Merchant = Depends(session_merchant), db: Session = Depends(get_db)):
    lang = _lang(body.language, m)
    text = body.text
    # The page may hand us English (a card, a table) while the merchant reads Tamil: speak it in their language.
    if lang in NATIVE or lang == "hi":
        try:
            text = sarvam.translate(db, text, lang, merchant_id=m.id)
        except Exception:
            db.rollback()
    try:
        audios = sarvam.tts(text, lang, m.id)
    except sarvam.VoiceUnavailable as e:
        _unavailable(e)
    return {"language": lang, "mime": "audio/mpeg", "audios": audios, "text": text}


@router.post("/voice/stt")
def voice_stt(language: str | None = Query(None), audio: bytes = Depends(audio_body), m: Merchant = Depends(session_merchant)):
    chosen = _lang(language, m)
    try:
        r = sarvam.stt(audio, chosen, m.id)
    except sarvam.VoiceUnavailable as e:
        _unavailable(e)
    return {"transcript": r["transcript"], "heard_language": from_sarvam(r["language_code"], chosen), "language_code": r["language_code"]}


@router.post("/voice/ask")
def voice_ask(language: str | None = Query(None), session_id: str | None = Query(None, max_length=40), speak: bool = Query(False),
              audio: bytes = Depends(audio_body), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    """One round trip for a spoken question: speech -> text -> Saathi -> answer (+ audio) in the merchant's language."""
    chosen = _lang(language, m)
    try:
        heard = sarvam.stt(audio, chosen, m.id)
    except sarvam.VoiceUnavailable as e:
        _unavailable(e)
    transcript = heard["transcript"]
    lang = from_sarvam(heard["language_code"], chosen)
    if not transcript:
        return {"transcript": "", "language": lang, "reply": "", "audios": [], "navigate": None, "pending_actions": [],
                "session_id": session_id, "heard_nothing": True}

    english = sarvam.to_english(transcript, lang, m.id) if lang in NATIVE or lang == "hi" else transcript
    target = nav_target(transcript, english)
    if target:
        label = target.replace("_", " ")
        reply = sarvam.translate(db, f"Opening {label}.", lang, merchant_id=m.id) if lang in NATIVE or lang == "hi" else f"Opening {label}."
        out = {"transcript": transcript, "language": lang, "reply": reply, "navigate": target, "pending_actions": [],
               "session_id": session_id, "engine": "nav"}
    else:
        r = agent_mod.respond(db, m, transcript, session_id, lang)
        out = {"transcript": transcript, "language": r.get("language", lang), "reply": r["reply"], "navigate": None,
               "suggest_tab": INTENT_TAB.get(r.get("intent", "")), "pending_actions": r.get("pending_actions", []),
               "session_id": r["session_id"], "engine": r.get("engine")}
    out["audios"], out["mime"] = [], "audio/mpeg"
    if speak and out["reply"]:
        try:
            out["audios"] = sarvam.tts(out["reply"], out["language"], m.id)
        except sarvam.VoiceUnavailable as e:  # the text answer still arrives; the browser can read it aloud
            out["tts_error"] = str(e)
    return out


__all__ = ["router", "LANGUAGES"]
