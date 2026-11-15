"""Sarvam AI: translation, speech-to-text and text-to-speech for Indian languages.

Design rules
- Never break the app: every public function degrades (returns the original text / raises VoiceUnavailable that the
  API turns into a clean 503) instead of surfacing a provider error.
- Pay once: translations are cached in the database, numbers are templated out ("{1} payments") so a changing count
  does not create a new translation, and many short strings share one API call.
- Bounded spend: a per-merchant daily character budget for translation and speech."""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import clock, config
from ..languages import LANGUAGES, NATIVE, sarvam_code
from ..models import TranslationCache

log = logging.getLogger("dukaan.sarvam")

BASE = "https://api.sarvam.ai"
TRANSLATE_MODEL = "sarvam-translate:v1"
TRANSLATE_MAX = 1800          # API limit is 2000 characters per call
TTS_MAX = 1400                # hard ceiling per request (bulbul:v3 accepts 2500)
STT_MAX_BYTES = 4 * 1024 * 1024
DAILY_CHARS = int(__import__("os").getenv("SARVAM_DAILY_CHARS", "400000"))  # per merchant: translation + speech text

_client: httpx.Client | None = None
_lock = threading.Lock()
_usage: dict[tuple[int, str], int] = {}
_tts_cache: "OrderedDict[tuple[str, str], list[str]]" = OrderedDict()
# numbers and brand names pass through translation untouched ("Saathi" must never become another word)
NUM = re.compile(r"Dukaan Saathi|Saathi|Paytm|₹?\d[\d,]*(?:\.\d+)?%?")
INDIC = re.compile(r"[ऀ-෿]")


class VoiceUnavailable(Exception):
    """Sarvam is not configured, out of budget, or failed. Callers fall back (browser voice / English text)."""


def available() -> bool:
    return bool(config.SARVAM_API_KEY)


def _http() -> httpx.Client:
    global _client
    with _lock:
        if _client is None:
            # retries=2: the transport quickly re-tries a failed *connection* (never a sent request)
            _client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(25.0, connect=4.0),
                                   transport=httpx.HTTPTransport(retries=2))
        return _client


def _charge(merchant_id: int | None, chars: int) -> None:
    if merchant_id is None or chars <= 0:
        return
    key = (merchant_id, clock.today().isoformat())
    with _lock:
        used = _usage.get(key, 0)
        if used + chars > DAILY_CHARS:
            raise VoiceUnavailable("daily_budget")
        _usage[key] = used + chars
        if len(_usage) > 5000:  # forget old days
            for k in [k for k in _usage if k[1] != key[1]]:
                _usage.pop(k, None)


class _Limiter:
    """Sliding one-minute window per Sarvam API (limits are per account: 60/min on pay-as-you-go). Interactive work
    (a spoken question, a chat reply) may use the whole budget; background work (translating page labels) leaves a
    reserve so it can never starve the merchant's voice."""

    def __init__(self, per_min: int, reserve: int):
        self.per_min, self.reserve = per_min, reserve
        self.sent: list[float] = []
        self.cool_until = 0.0
        self.lock = threading.Lock()

    def acquire(self, interactive: bool, max_wait: float) -> None:
        deadline = time.monotonic() + max_wait
        allowed = self.per_min if interactive else self.per_min - self.reserve
        while True:
            with self.lock:
                now = time.monotonic()
                self.sent = [t for t in self.sent if now - t < 60]
                if now >= self.cool_until and len(self.sent) < allowed:
                    self.sent.append(now)
                    return
                wait = max(self.cool_until - now, (self.sent[0] + 60 - now) if len(self.sent) >= allowed else 0, 0.05)
            if time.monotonic() + wait > deadline:
                raise VoiceUnavailable("rate_limited")
            time.sleep(min(wait, 0.5))

    def backoff(self, seconds: float) -> None:
        with self.lock:
            self.cool_until = max(self.cool_until, time.monotonic() + seconds)


RATE_PER_MIN = int(__import__("os").getenv("SARVAM_RATE_PER_MIN", "55"))
_limits = {p: _Limiter(RATE_PER_MIN, reserve=15) for p in ("/translate", "/text-to-speech", "/speech-to-text")}


def _post(path: str, *, json: dict | None = None, files: dict | None = None, data: dict | None = None,
          interactive: bool = True) -> dict:
    global _client
    if not available():
        raise VoiceUnavailable("not_configured")
    headers = {"api-subscription-key": config.SARVAM_API_KEY}
    limiter = _limits.get(path)
    last = "error"
    for attempt in range(3):
        if limiter:
            limiter.acquire(interactive, max_wait=20.0 if interactive else 4.0)
        try:
            r = _http().post(path, json=json, files=files, data=data, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            # could not reach Sarvam even after the transport's quick re-tries: drop the pool (a fresh client re-resolves
            # DNS and may land on the other server) and stop, so the merchant is not left waiting
            with _lock:
                _client = None
            log.warning("sarvam %s unreachable: %s", path, type(e).__name__)
            raise VoiceUnavailable("unreachable")
        except httpx.HTTPError as e:  # read timeout / dropped connection: worth one more try
            last = type(e).__name__
        else:
            if r.status_code == 200:
                return r.json()
            last = "rate_limited" if r.status_code == 429 else f"http_{r.status_code}"
            if r.status_code == 429 and limiter:
                limiter.backoff(2.0 * (attempt + 1))  # everyone pauses, not just this request
                if not interactive:
                    break  # page labels can wait; the browser asks again shortly
            elif r.status_code not in (500, 502, 503, 504):
                log.warning("sarvam %s failed: %s %s", path, r.status_code, r.text[:200])
                break  # bad request / auth / no credits: retrying will not help
        time.sleep(0.4 * (attempt + 1) ** 2)
    raise VoiceUnavailable(last)


# ---------------------------------------------------------------- translation

def template(text: str) -> tuple[str, list[str]]:
    """'₹16,182 from 116 payments' -> ('{1} from {2} payments', ['₹16,182', '116'])."""
    nums: list[str] = []

    def sub(m: re.Match) -> str:
        nums.append(m.group(0))
        return "{%d}" % len(nums)
    return NUM.sub(sub, text), nums


def fill(text: str, nums: list[str]) -> str | None:
    """Put numbers back; None if the translation lost or invented a placeholder."""
    for i, n in enumerate(nums, 1):
        if text.count("{%d}" % i) != 1:
            return None
        text = text.replace("{%d}" % i, n)
    return None if re.search(r"\{\d+\}", text) else text


CACHE_VERSION = "3"  # bump when the glossary changes so stale translations are not reused


def _hash(s: str) -> str:
    return hashlib.sha1((CACHE_VERSION + "|" + s).encode()).hexdigest()


# Short UI labels have no context: "Stock" comes back as "shares", "Settlements" as "habitations". Send a clearer
# English phrase instead (the cache and the page still use the original label).
CLARIFY_EXACT = {
    "Out": "Sold out", "Low": "Running low", "OK": "Enough", "Stock": "Shop inventory",
    "Win-back offer": "Offer to bring back old customers",
}
CLARIFY_WORDS = [(re.compile(r"\bstock\b", re.I), "inventory"), (re.compile(r"\bsettlements\b", re.I), "bank payouts"),
                 (re.compile(r"\bsettlement\b", re.I), "bank payout"), (re.compile(r"\bticket\b", re.I), "bill")]


def clarify(s: str, exact: bool = True) -> str:
    if exact and s in CLARIFY_EXACT:
        return CLARIFY_EXACT[s]
    for rx, rep in CLARIFY_WORDS:
        s = rx.sub(rep, s)
    return s


def _call_translate(text: str, src: str, tgt: str, interactive: bool = True) -> str:
    out = _post("/translate", json={"input": text, "source_language_code": sarvam_code(src), "target_language_code": sarvam_code(tgt),
                                     "model": TRANSLATE_MODEL}, interactive=interactive)
    return (out.get("translated_text") or "").strip()


def _translate_chunk(items: list[str], src: str, tgt: str, ui: bool = False, interactive: bool = True) -> dict[str, str]:
    """Several one-line strings in one call, joined by newlines. If the lines do not come back one-for-one, the chunk is
    split in half and retried (a few calls, never one per string). Rate limits are not retried here."""
    send = {k: clarify(k, exact=ui) for k in items}
    try:
        out = _call_translate("\n".join(send[k] for k in items), src, tgt, interactive)
    except VoiceUnavailable:
        return {}
    lines = [ln.strip() for ln in out.split("\n") if ln.strip()]
    if len(lines) == len(items):
        return dict(zip(items, lines))
    if len(items) == 1:
        return {items[0]: out.strip()} if out.strip() else {}
    mid = len(items) // 2
    return {**_translate_chunk(items[:mid], src, tgt, ui, interactive), **_translate_chunk(items[mid:], src, tgt, ui, interactive)}


def translate_many(db: Session, texts: list[str], tgt: str, src: str = "en", merchant_id: int | None = None,
                   templated: bool = True, interactive: bool = True) -> list[str]:
    return translate_status(db, texts, tgt, src, merchant_id, templated, interactive)[0]


def translate_status(db: Session, texts: list[str], tgt: str, src: str = "en", merchant_id: int | None = None,
                     templated: bool = True, interactive: bool = True) -> tuple[list[str], list[int]]:
    """Translate a list of strings (order kept). Anything that cannot be translated comes back unchanged.
    templated: swap numbers for {1}, {2} so "116 payments" and "117 payments" share one translation (UI labels).
    Sentences (replies, briefing) are translated with their real numbers, which reads more naturally."""
    if tgt == src or tgt not in LANGUAGES or tgt in ("en", "hinglish") or not texts:
        return list(texts), []
    prepared = {}  # original -> (template, numbers)
    for t in texts:
        # only English text is translated: numbers alone, or text already in an Indian script, stay as they are
        if t and t.strip() and t not in prepared and re.search(r"[A-Za-z]{2,}", t) and not INDIC.search(t):
            tpl = template(t.strip()) if templated else (t.strip(), [])
            if re.search(r"[A-Za-z]{2,}", tpl[0]):  # e.g. just "Saathi" or "₹500": nothing left to translate
                prepared[t] = tpl
    keys = {tpl for tpl, _ in prepared.values()}
    cached: dict[str, str] = {}
    if keys:
        hashes = {_hash(k): k for k in keys}
        for row in db.query(TranslationCache).filter(TranslationCache.tgt_lang == tgt, TranslationCache.src_lang == src,
                                                     TranslationCache.src_hash.in_(list(hashes))):
            if row.src in keys:
                cached[row.src] = row.out
    missing = [k for k in keys if k not in cached]
    retryable = bool(missing) and available()
    if missing and available():
        try:
            _charge(merchant_id, sum(len(k) for k in missing))
        except VoiceUnavailable:
            missing, retryable = [], False  # daily budget used up: English until tomorrow
        single = [k for k in missing if "\n" not in k and len(k) <= 400]
        multi = [k for k in missing if k not in single]
        chunks, cur, size = [], [], 0
        for k in single:
            if cur and (size + len(k) + 1 > TRANSLATE_MAX or len(cur) >= 80):
                chunks.append(cur)
                cur, size = [], 0
            cur.append(k)
            size += len(k) + 1
        if cur:
            chunks.append(cur)
        chunks += [[k] for k in multi if len(k) <= TRANSLATE_MAX]
        fresh: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for part in pool.map(lambda c: _translate_chunk(c, src, tgt, templated, interactive), chunks):
                fresh.update(part)
        for k, v in fresh.items():
            if not v or (re.findall(r"\{\d+\}", k) and sorted(re.findall(r"\{\d+\}", k)) != sorted(re.findall(r"\{\d+\}", v))):
                continue  # empty or placeholders damaged: do not cache a broken string
            cached[k] = v
            db.add(TranslationCache(src_lang=src, tgt_lang=tgt, src_hash=_hash(k), src=k, out=v, created_at=clock.now()))
            try:
                db.commit()
            except IntegrityError:  # another request cached it first
                db.rollback()
    out, failed = [], []
    for i, t in enumerate(texts):
        if t not in prepared:
            out.append(t)
            continue
        tpl, nums = prepared[t]
        tr = cached.get(tpl)
        filled = fill(tr, nums) if tr else None
        lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
        out.append(lead + filled + trail if filled else t)
        if tr is None and retryable:
            failed.append(i)  # not translated this time (busy / rate limited): worth asking again shortly
    return out, failed


def translate(db: Session, text: str, tgt: str, src: str = "en", merchant_id: int | None = None) -> str:
    if not text or not text.strip():
        return text
    # long replies: translate line by line so each piece stays under the API limit and stays cacheable
    lines = text.split("\n")
    return "\n".join(translate_many(db, lines, tgt, src, merchant_id, templated=False))


def to_english(text: str, src: str, merchant_id: int | None = None) -> str:
    """The merchant's own words (not cached: they are unique). Returns the input unchanged on failure."""
    text = (text or "").strip()
    if not text or src in ("en", "hinglish") or not re.search(r"[^\x00-\x7F]", text):
        return text  # already Latin script: English or romanised
    try:
        _charge(merchant_id, len(text))
        return _call_translate(text[:TRANSLATE_MAX], src, "en") or text
    except Exception as e:  # never let translation break a question: answer the original words instead
        log.info("to_english fell back to original text: %s", e)
        return text


# ---------------------------------------------------------------- speech

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def _speakable(text: str) -> str:
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_#`>|•▲▼→←]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _chunks(text: str, limit: int = TTS_MAX) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?।])\s+", text):
        while len(sent) > limit:  # one giant sentence: hard split on a space
            cut = sent.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append((cur + " " + sent[:cut]).strip()) if cur else parts.append(sent[:cut])
            cur, sent = "", sent[cut:].strip()
        if len(cur) + len(sent) + 1 > limit:
            parts.append(cur)
            cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur)
    return [p for p in parts if p.strip()]


TTS_PIECE = 320  # short pieces are synthesised in parallel: the first one is ready (and playing) sooner


def tts(text: str, lang: str, merchant_id: int | None = None) -> list[str]:
    """Base64 MP3 clips, to be played in order. Raises VoiceUnavailable."""
    text = _speakable(text or "")[:6000]
    if not text:
        raise VoiceUnavailable("empty")
    key = (lang, text)
    with _lock:
        if key in _tts_cache:
            _tts_cache.move_to_end(key)
            return _tts_cache[key]
    _charge(merchant_id, len(text))
    code = sarvam_code(lang)
    pieces = _chunks(text, TTS_PIECE)

    def one(p: str) -> list[str]:
        return _post("/text-to-speech", json={"text": p, "language_code": code, "output_audio_codec": "mp3"}).get("audios") or []
    with ThreadPoolExecutor(max_workers=4) as pool:
        audios = [a for r in pool.map(one, pieces) for a in r]
    if not audios:
        raise VoiceUnavailable("no_audio")
    with _lock:
        _tts_cache[key] = audios
        while len(_tts_cache) > 64:
            _tts_cache.popitem(last=False)
    return audios


def _sniff(audio: bytes) -> tuple[str, str]:
    if audio[:4] == b"RIFF":
        return "audio.wav", "audio/wav"
    if audio[:4] == b"\x1aE\xdf\xa3":
        return "audio.webm", "audio/webm"
    if audio[4:8] == b"ftyp":
        return "audio.m4a", "audio/mp4"
    if audio[:4] == b"OggS":
        return "audio.ogg", "audio/ogg"
    if audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "audio.mp3", "audio/mpeg"
    return "audio.wav", "audio/wav"


def stt(audio: bytes, hint: str | None = None, merchant_id: int | None = None) -> dict:
    """{'transcript', 'language_code'}; language is auto-detected so a merchant can speak any Indian language."""
    if not audio or len(audio) < 1000:
        raise VoiceUnavailable("too_short")
    if len(audio) > STT_MAX_BYTES:
        raise VoiceUnavailable("too_long")
    _charge(merchant_id, 200)  # flat charge per clip
    name, mime = _sniff(audio)
    out = _post("/speech-to-text", files={"file": (name, audio, mime)}, data={"language_code": "unknown"})
    return {"transcript": (out.get("transcript") or "").strip(), "language_code": out.get("language_code")}


__all__ = ["available", "translate", "translate_many", "to_english", "tts", "stt", "VoiceUnavailable", "NATIVE"]
