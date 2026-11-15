"""Market news and the seasonal / financial advisor. News is faked; no LLM key in tests (template note)."""
from datetime import datetime, timedelta, timezone

from app.models import Merchant
from app.services import advisor, news

H = {"X-Merchant-Id": "1"}
NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


def _item(title, source="Business Standard", hours=5, link=None):
    return {"title": title, "source": source, "link": link or f"https://example.org/{abs(hash(title))}", "published": NOW - timedelta(hours=hours)}


HEADLINES = [
    _item("India's retail sugar prices remain elevated as demand rises", "ChiniMandi"),
    _item("Sugar prices rise again ahead of the wedding season", "Mint"),
    _item("Sugar prices hike: what it means for traders", "Upstox"),
    _item("Edible oil prices fall as imports surge", "Reuters"),
    _item("HUL shares jump 4%, target price raised by brokerage", "Moneycontrol"),        # share-market noise
    _item("Actor visits a famous Mumbai sweet shop with friends", "Filmy"),               # not about trade
    _item("소금 가격 상승", "Chosun"),                                                    # not English
    _item("Kirana stores see festive demand jump as UPI payments grow", "Economic Times"),
    _item("Old sugar story about prices rising", "Old News", hours=24 * 30),            # too old
]


def _fake_news(monkeypatch, items=HEADLINES):
    monkeypatch.setattr(news, "_fetch", lambda q: [dict(x) for x in items])
    news._cache.clear()


def test_news_is_relevant_real_and_clean(db, monkeypatch):
    _fake_news(monkeypatch)
    n = news.for_merchant(db, db.get(Merchant, 1))
    titles = [x["title"] for x in n["items"]]
    assert not any("shares" in t or "Actor" in t or "가격" in t or "Old sugar" in t for t in titles)
    assert any("Kirana" in t for t in titles)
    assert sum("ugar" in t for t in titles) <= 2  # variety: at most two stories per commodity
    assert all(x["link"].startswith("https://") and x["source"] for x in n["items"])
    sig = {s["commodity"]: s for s in n["price_signals"]}
    assert sig["sugar"]["direction"] == "up" and sig["sugar"]["sources"]
    assert sig["edible oil"]["direction"] == "down"


def test_news_offline_keeps_last_good_copy(db, monkeypatch):
    _fake_news(monkeypatch)
    m = db.get(Merchant, 1)
    assert news.for_merchant(db, m)["items"]
    monkeypatch.setattr(news, "_fetch", lambda q: (_ for _ in ()).throw(OSError("offline")))
    news._cache["kirana"] = (0, news._cache["kirana"][1])  # expired
    assert news.for_merchant(db, m)["items"]  # still shows the last headlines


def test_news_endpoint_with_no_network(client):
    r = client.get("/api/news", headers=H)
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["available"] is False


def test_festival_stock_up_with_price_news(db, monkeypatch):
    _fake_news(monkeypatch)
    p = advisor.plan(db, db.get(Merchant, 1))
    assert p["season"]["festivals"][0]["name"] == "Dev Diwali"
    sugar = next(x for x in p["stock_moves"] if x["item"] == "Sugar")
    assert sugar["move"] == "increase" and sugar["qty"] > 0 and sugar["reason"] == "Dev Diwali"
    assert "rising" in sugar["advice"] and sugar["price_signal"]["sources"]
    assert sugar["by"] <= "2026-11-24"


def test_winter_slows_cold_drinks(db):
    p = advisor.plan(db, db.get(Merchant, 1), with_news=False)
    cd = [x for x in p["stock_moves"] if x["item"].startswith("Cold Drink")]
    assert not cd or cd[0]["move"] == "reduce"


def test_discounts_respect_the_merchant_cap(db):
    m = db.get(Merchant, 1)
    m.max_offer_discount_pct = 3
    db.commit()
    p = advisor.plan(db, m, with_news=False)
    assert p["slow_sellers"] and all(x["discount_pct"] <= 3 for x in p["slow_sellers"])


def test_salon_gets_capacity_advice_not_stock(db):
    p = advisor.plan(db, db.get(Merchant, 3), with_news=False)
    assert p["stock_moves"] == []


def test_money_advice_puts_problems_first(db):
    p = advisor.plan(db, db.get(Merchant, 2), with_news=False)
    tones = [x["tone"] for x in p["money"]]
    assert tones == sorted(tones, key=lambda t: {"bad": 0, "warn": 1, "good": 2}[t])
    assert any(x["id"] == "cash_gap" for x in p["money"])  # Sharma Sweets has a cash gap
    fb = next((x for x in p["money"] if x["id"] == "festival_buy"), None)
    assert fb is None or fb["tone"] == "warn"  # never "comfortably affordable" during a cash gap


def test_plan_endpoint_and_template_note_cached(client):
    r = client.get("/api/growth/plan", headers=H).json()
    assert r["note"]["source"] == "template" and "•" in r["note"]["text"]
    r2 = client.get("/api/growth/plan", headers=H).json()
    assert r2["note"]["cached"] is True


def test_plan_respects_consent(client):
    client.put("/api/consent/transactions", headers=H, json={"granted": False})
    assert client.get("/api/growth/plan", headers=H).status_code == 403


def test_chat_season_and_news(client, monkeypatch):
    _fake_news(monkeypatch)
    r = client.post("/api/chat", headers=H, json={"message": "Dev Diwali ke liye kya mangwau?", "language": "en"}).json()
    assert r["intent"] == "season_plan" and "Sugar" in r["reply"]
    r = client.post("/api/chat", headers=H, json={"message": "aaj ki news", "language": "en"}).json()
    assert r["intent"] == "news" and "(" in r["reply"]
