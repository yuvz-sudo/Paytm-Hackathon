"""Languages, translation and voice. Sarvam is faked: tests never call the real API."""
import pytest

from app import config
from app.agent.navigate import nav_target
from app.services import sarvam

H = {"X-Merchant-Id": "1"}
WAV = b"RIFF" + b"\0" * 4000


class FakeSarvam:
    def __init__(self):
        self.calls = []
        self.transcript = "Kal ki sales kitni thi?"
        self.heard = "hi-IN"
        self.fail = False

    def __call__(self, path, json=None, files=None, data=None, interactive=True):
        self.calls.append(path)
        if self.fail:
            raise sarvam.VoiceUnavailable("http_500")
        if path == "/translate":
            if json["target_language_code"] == "en-IN":
                return {"translated_text": "How much was sold yesterday?"}
            return {"translated_text": "\n".join("[" + json["target_language_code"][:2] + "] " + ln for ln in json["input"].split("\n"))}
        if path == "/text-to-speech":
            return {"audios": ["QUJD"]}
        if path == "/speech-to-text":
            return {"transcript": self.transcript, "language_code": self.heard}
        raise AssertionError(path)


@pytest.fixture()
def fake(monkeypatch):
    f = FakeSarvam()
    monkeypatch.setattr(config, "SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(sarvam, "_post", f)
    sarvam._tts_cache.clear()
    sarvam._usage.clear()
    for lim in sarvam._limits.values():
        lim.sent.clear()
        lim.cool_until = 0
    return f


def test_languages_listed(client):
    r = client.get("/api/languages").json()
    codes = {x["code"] for x in r["languages"]}
    assert {"en", "hi", "hinglish", "ta", "te", "bn", "mr", "gu", "kn", "ml", "pa", "od"} <= codes


def test_merchant_can_choose_any_supported_language(client):
    assert client.put("/api/merchant/language", headers=H, json={"language": "ml"}).status_code == 200
    assert client.put("/api/merchant/language", headers=H, json={"language": "xx"}).status_code == 422


def test_ui_translation_is_cached_and_numbers_templated(client, fake):
    r = client.post("/api/i18n/translate", headers=H, json={"language": "ta", "texts": ["116 payments", "View all", "₹1,200"]}).json()
    assert r["translations"] == ["[ta] 116 payments", "[ta] View all", "₹1,200"]  # a bare amount is not sent
    n = len(fake.calls)
    r = client.post("/api/i18n/translate", headers=H, json={"language": "ta", "texts": ["117 payments", "View all"]}).json()
    assert r["translations"] == ["[ta] 117 payments", "[ta] View all"]
    assert len(fake.calls) == n  # served from the cache, no new API call


def test_ui_translation_english_and_failure_return_original(client, fake):
    assert client.post("/api/i18n/translate", headers=H, json={"language": "en", "texts": ["Stock"]}).json()["translations"] == ["Stock"]
    fake.fail = True
    r = client.post("/api/i18n/translate", headers=H, json={"language": "bn", "texts": ["Stock running low"]})
    assert r.status_code == 200 and r.json()["translations"] == ["Stock running low"]


def test_damaged_placeholders_are_not_cached(db, fake, monkeypatch):
    monkeypatch.setattr(sarvam, "_post", lambda *a, **k: {"translated_text": "broken"})
    assert sarvam.translate_many(db, ["{n} 5 items"], "ta")[0] == "{n} 5 items"
    assert sarvam.translate_many(db, ["5 items"], "ta")[0] == "5 items"  # '{1}' lost -> keep English


def test_chat_in_tamil_translates_both_ways(client, fake):
    r = client.post("/api/chat", headers=H, json={"message": "நேற்று எவ்வளவு விற்பனை ஆனது?", "language": "ta"}).json()
    assert r["intent"] == "sales" and r["language"] == "ta"
    assert r["reply"].startswith("[ta] ")
    assert r["understood_as"] == "How much was sold yesterday?"


def test_chat_in_tamil_still_answers_when_sarvam_is_down(client, fake):
    fake.fail = True
    r = client.post("/api/chat", headers=H, json={"message": "Yesterday's sales", "language": "ta"})
    assert r.status_code == 200 and r.json()["reply"]


def test_tts_and_stt(client, fake):
    r = client.post("/api/voice/tts", headers=H, json={"text": "Hello", "language": "en"}).json()
    assert r["audios"] == ["QUJD"] and r["mime"] == "audio/mpeg"
    r = client.post("/api/voice/stt?language=hinglish", headers=H, content=WAV).json()
    assert r["transcript"] == "Kal ki sales kitni thi?" and r["heard_language"] == "hinglish"


def test_voice_unavailable_is_a_clean_503(client):
    sarvam._tts_cache.clear()
    assert not sarvam.available()  # tests run without a key
    r = client.post("/api/voice/tts", headers=H, json={"text": "Hello", "language": "en"})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "voice_unavailable"


def test_audio_size_limits(client, fake):
    assert client.post("/api/voice/stt", headers=H, content=b"x" * 10).status_code == 422
    assert client.post("/api/voice/stt", headers=H, content=b"x" * (sarvam.STT_MAX_BYTES + 10)).status_code == 413


def test_voice_ask_answers_question(client, fake):
    r = client.post("/api/voice/ask?language=hinglish&speak=true", headers=H, content=WAV).json()
    assert r["transcript"] == "Kal ki sales kitni thi?" and r["reply"] and r["navigate"] is None
    assert r["audios"] == ["QUJD"] and r["suggest_tab"] == "transactions"


def test_voice_ask_navigates(client, fake):
    fake.transcript = "स्टॉक पेज खोलो"
    r = client.post("/api/voice/ask?language=hinglish", headers=H, content=WAV).json()
    assert r["navigate"] == "stock"


def test_voice_ask_heard_nothing(client, fake):
    fake.transcript = ""
    r = client.post("/api/voice/ask", headers=H, content=WAV).json()
    assert r["heard_nothing"] is True


def test_nav_only_for_explicit_open():
    assert nav_target("open stock") == "stock"
    assert nav_target("udhaar dikhao") == "udhaar"
    assert nav_target("how much stock is left?") is None
    assert nav_target("show me the customers page") == "customers"


def test_briefing_in_native_language(client, fake):
    client.put("/api/merchant/language", headers=H, json={"language": "te"})
    b = client.get("/api/briefing", headers=H).json()
    assert b["translated_to"] == "te" and all(ln.startswith("[te] ") for ln in b["script_lines"] if any(c.isalpha() for c in ln))


def test_speech_chunks_stay_under_limit():
    text = "This is a sentence. " * 200
    parts = sarvam._chunks(text, 300)
    assert all(len(p) <= 300 for p in parts) and "".join(parts).replace(" ", "") == text.replace(" ", "")


def test_rate_limited_ui_strings_are_marked_for_retry(client, fake, monkeypatch):
    def busy(*a, **k):
        raise sarvam.VoiceUnavailable("rate_limited")
    monkeypatch.setattr(sarvam, "_post", busy)
    r = client.post("/api/i18n/translate", headers=H, json={"language": "kn", "texts": ["Never translated before", "₹50"]}).json()
    assert r["translations"] == ["Never translated before", "₹50"] and r["retry"] == [0]


def test_background_work_leaves_a_reserve_for_voice():
    lim = sarvam._Limiter(per_min=5, reserve=2)
    for _ in range(3):
        lim.acquire(interactive=False, max_wait=0.1)
    try:
        lim.acquire(interactive=False, max_wait=0.1)
        assert False, "background work should have been refused"
    except sarvam.VoiceUnavailable:
        pass
    lim.acquire(interactive=True, max_wait=0.1)  # the merchant's voice still gets through
    lim.acquire(interactive=True, max_wait=0.1)


def test_batch_with_mismatched_lines_is_split_not_exploded(monkeypatch):
    calls = []

    def fake(path, json=None, **k):
        calls.append(json["input"])
        lines = json["input"].split("\n")
        return {"translated_text": "x" if len(lines) > 2 else "\n".join("t:" + ln for ln in lines)}
    monkeypatch.setattr(sarvam, "_post", fake)
    out = sarvam._translate_chunk([f"label {i}" for i in range(8)], "en", "ta")
    assert len(out) == 8 and len(calls) <= 7  # halving, not one call per label


def test_unreachable_sarvam_fails_fast_with_clear_reason(client, monkeypatch):
    import httpx
    import time as _t
    monkeypatch.setattr(config, "SARVAM_API_KEY", "test-key")

    class Down:
        def post(self, *a, **k):
            raise httpx.ConnectTimeout("no route")
    monkeypatch.setattr(sarvam, "_http", lambda: Down())
    for lim in sarvam._limits.values():
        lim.sent.clear()
        lim.cool_until = 0
    t = _t.monotonic()
    r = client.post("/api/voice/ask?language=en", headers=H, content=WAV)
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "unreachable"
    assert _t.monotonic() - t < 2  # no long retry loop on top of the transport's own quick re-tries
