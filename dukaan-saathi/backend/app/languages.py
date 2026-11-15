"""The languages Dukaan Saathi speaks. One list, used by the API, the agent and voice.

en / hi / hinglish have hand-written replies (i18n.py). The other Indian languages ("native") are served through
Sarvam AI: the merchant's words are translated to English, answered, and the answer translated back."""
from __future__ import annotations

# code -> (English name, native name, Sarvam BCP-47 code)
LANGUAGES: dict[str, tuple[str, str, str]] = {
    "hinglish": ("Hinglish", "Hinglish", "hi-IN"),
    "hi": ("Hindi", "हिन्दी", "hi-IN"),
    "en": ("English", "English", "en-IN"),
    "bn": ("Bengali", "বাংলা", "bn-IN"),
    "gu": ("Gujarati", "ગુજરાતી", "gu-IN"),
    "kn": ("Kannada", "ಕನ್ನಡ", "kn-IN"),
    "ml": ("Malayalam", "മലയാളം", "ml-IN"),
    "mr": ("Marathi", "मराठी", "mr-IN"),
    "od": ("Odia", "ଓଡ଼ିଆ", "od-IN"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", "pa-IN"),
    "ta": ("Tamil", "தமிழ்", "ta-IN"),
    "te": ("Telugu", "తెలుగు", "te-IN"),
}
SUPPORTED = set(LANGUAGES)
NATIVE = SUPPORTED - {"en", "hi", "hinglish"}  # need the Sarvam translation layer
# Sarvam code (or its prefix) -> app code, for speech that was auto-detected
_FROM_SARVAM = {v[2].split("-")[0]: k for k, v in LANGUAGES.items() if k != "hinglish"}


def sarvam_code(lang: str) -> str:
    return LANGUAGES.get(lang, LANGUAGES["en"])[2]


def from_sarvam(code: str | None, chosen: str) -> str:
    """Map a detected speech language to the reply language. Hindi or English speech keeps a Hinglish merchant in Hinglish."""
    if not code:
        return chosen
    app = _FROM_SARVAM.get(code.split("-")[0].lower())
    if not app:
        return chosen
    if chosen == "hinglish" and app in ("hi", "en"):
        return "hinglish"
    return app


def listing() -> list[dict]:
    return [{"code": k, "name": v[0], "native": v[1], "voice": True} for k, v in LANGUAGES.items()]
