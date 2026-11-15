"""Ask Saathi conversations survive reloads for 7 days, then are deleted."""
from datetime import timedelta

from app import clock, config
from app.models import ChatMessage
from app.services import sarvam

H = {"X-Merchant-Id": "1"}


def test_recent_returns_latest_conversation_in_order(client):
    sid = client.post("/api/chat", headers=H, json={"message": "Yesterday's sales", "language": "en"}).json()["session_id"]
    client.post("/api/chat", headers=H, json={"message": "What's low in stock?", "session_id": sid, "language": "en"})
    r = client.get("/api/chat/recent", headers=H).json()
    assert r["session_id"] == sid and r["retention_days"] == 7
    assert [m["role"] for m in r["messages"]] == ["user", "assistant", "user", "assistant"]
    assert r["messages"][0]["text"] == "Yesterday's sales" and r["messages"][1]["lang"] == "en"


def test_chats_older_than_7_days_are_deleted(client, db):
    old = clock.now() - timedelta(days=config.CHAT_RETENTION_DAYS + 1)
    db.add(ChatMessage(merchant_id=1, session_id="oldsession", role="user", content="ancient question", ts=old, meta={}))
    db.add(ChatMessage(merchant_id=2, session_id="other", role="user", content="other merchant", ts=old, meta={}))
    db.commit()
    r = client.get("/api/chat/recent", headers=H).json()
    assert r["messages"] == [] and r["session_id"] is None
    assert db.query(ChatMessage).filter_by(session_id="oldsession").count() == 0
    assert db.query(ChatMessage).filter_by(session_id="other").count() == 1  # only this merchant's chats were touched


def test_recent_chat_brings_back_pending_approvals(client):
    r = client.post("/api/chat", headers=H, json={"message": "order stock from supplier", "language": "en"}).json()
    assert r["pending_actions"]
    rec = client.get("/api/chat/recent", headers=H).json()
    cards = [a for m in rec["messages"] for a in m["actions"]]
    assert {a["id"] for a in cards} == {a["id"] for a in r["pending_actions"]}
    client.post(f"/api/actions/{cards[0]['id']}/approve", headers=H)
    rec = client.get("/api/chat/recent", headers=H).json()
    assert cards[0]["id"] not in {a["id"] for m in rec["messages"] for a in m["actions"]}  # decided: no stale card


def test_recent_is_per_merchant(client):
    client.post("/api/chat", headers=H, json={"message": "hello", "language": "en"})
    assert client.get("/api/chat/recent", headers={"X-Merchant-Id": "2"}).json()["messages"] == []


def test_tamil_chat_is_saved_as_the_merchant_saw_it(client, monkeypatch):
    monkeypatch.setattr(config, "SARVAM_API_KEY", "test-key")

    def fake(path, json=None, **k):
        if json["target_language_code"] == "en-IN":
            return {"translated_text": "How much was sold yesterday?"}
        return {"translated_text": "\n".join("[ta] " + x for x in json["input"].split("\n"))}
    monkeypatch.setattr(sarvam, "_post", fake)
    q = "நேற்று எவ்வளவு விற்பனை ஆனது?"
    client.post("/api/chat", headers=H, json={"message": q, "language": "ta"})
    msgs = client.get("/api/chat/recent", headers=H).json()["messages"]
    assert msgs[0]["text"] == q and msgs[1]["text"].startswith("[ta] ") and msgs[1]["lang"] == "ta"
