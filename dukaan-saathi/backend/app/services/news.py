"""Market news for the merchant's line of business, from real publishers (Google News RSS: headline, source, date, link).

Nothing here is written by an LLM: headlines are shown as published, with the source and a link, so they can be checked.
Relevance comes from the shop's own catalogue (a kirana that sells sugar and atta sees sugar and wheat news) and its
business type, recent items rank higher, and share-market noise (stock prices, IPOs) is dropped.

Price signals: a headline that says a commodity the shop sells is getting dearer or cheaper ("sugar prices rise",
"edible oil prices fall") becomes a signal the Growth Advisor can use, always shown with its source."""
from __future__ import annotations

import email.utils
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from .. import clock
from ..models import Item, Merchant

log = logging.getLogger("dukaan.news")

FEED = "https://news.google.com/rss/search"
CACHE_SECONDS = 2 * 3600
MAX_AGE_DAYS = 10

# What each business cares about. Queries are deliberately India-specific and about the trade, not about companies' shares.
SEGMENT_QUERIES: dict[str, list[str]] = {
    "kirana": ['(kirana OR "grocery stores" OR "small retailers" OR FMCG) India demand',
               '("sugar prices" OR "wheat prices" OR "atta prices" OR "edible oil prices" OR "pulses prices" OR "rice prices") India',
               '(UPI OR GST) "small merchants" OR shopkeepers India'],
    "sweets": ['("sweet shops" OR "sweets demand" OR "mithai sales" OR "bakery industry" OR "festive demand") India',
               '("milk prices" OR "ghee prices" OR "sugar prices" OR "dry fruits prices" OR "khoya") India',
               '(FSSAI) sweets OR mithai OR "food safety" shops'],
    "salon": ['("salon industry" OR "beauty services market" OR "grooming market" OR "salon chain" OR "beauty and personal care") India',
              '("wedding season" demand OR "beauty products prices" OR "personal care prices") India',
              '(UPI OR GST) "small businesses" OR "service providers" India'],
    "pharmacy": ['(pharmacy OR chemists OR "medical stores") India',
                 '(NPPA OR "drug prices" OR "medicine prices") India',
                 '("e-pharmacy" OR "online pharmacy") chemists India'],
    "restaurant": ['(restaurants OR "food business" OR dhaba OR "cloud kitchen") India',
                   '("vegetable prices" OR "tomato prices" OR "onion prices" OR "cooking oil prices" OR "LPG price") India',
                   '(Swiggy OR Zomato) "restaurant partners" India'],
}
GENERIC = ['("small businesses" OR MSME OR shopkeepers) India', '(UPI OR GST) merchants India']

# Item words -> the commodity a headline would name (and what to search for)
COMMODITIES: dict[str, tuple[str, ...]] = {
    "sugar": ("sugar", "chini"), "wheat": ("atta", "wheat", "flour"), "edible oil": ("edible oil", "cooking oil", "sunflower oil", "mustard oil", "palm oil", "soybean oil", "soyabean oil"), "pulses": ("dal", "pulses", "toor", "chana"),
    "rice": ("rice", "basmati"), "milk": ("milk", "paneer", "curd"), "ghee": ("ghee",), "dry fruits": ("dry fruit", "kaju", "badam", "cashew"),
    "eggs": ("egg",), "onion": ("onion",), "tomato": ("tomato",), "tea": ("tea", "chai"), "salt": ("salt",), "spices": ("turmeric", "haldi", "masala"),
}
# Raw materials a business buys even if it does not sell them (their price moves its costs)
SEGMENT_INPUTS = {"sweets": {"milk", "sugar", "ghee", "dry fruits"}, "restaurant": {"onion", "tomato", "edible oil", "rice", "milk"},
                  "kirana": set(), "salon": set(), "pharmacy": set()}
UP = re.compile(r"\b(drive up|drives up|push up|pushes up|goes up|went up|higher|remain high|stay high|rise|rises|rising|rose|hike|hikes|hiked|surge|surges|jump|jumps|soar|soars|spike|elevated|costlier|dearer|up \d|increase[sd]?|climb|firm)\b", re.I)
DOWN = re.compile(r"\b(fall|falls|falling|fell|drop|drops|dropped|decline|declines|cut|cuts|ease|eases|easing|cheaper|slump|slide|dip|dips|soften|lower)\b", re.I)
# A headline must be about trade: prices, demand, sales, supply, the market... (drops celebrity and lifestyle pieces)
BIZ = re.compile(r"\b(demand|sales|sell|selling|prices?|market|markets|business|businesses|industry|festive|season|traders?|shops?|shopkeepers|retail|"
                 r"retailers?|consumers?|inflation|costs?|gst|upi|msme|wholesale|supply|imports?|exports?|production|rates?|margins?|"
                 r"spending|revenue|growth|regulation|rules?|licen[cs]e|fssai|nppa)\b", re.I)
NOISE = re.compile(r"\b(shares?|stock price|target price|sensex|nifty|ipo|q[1-4] results|quarterly results|dividend|brokerage|buy rating|sell rating|market cap)\b", re.I)

def direction(title: str) -> str | None:
    """'up' / 'down' for what a headline says about prices. The words right after "price(s)/rates" decide
    ("oil prices fall as imports surge" is down); otherwise the whole headline, if it is not mixed."""
    m = re.search(r"\b(prices?|rates?|costs?)\b((?:\W+\w+){0,2})", title, re.I)
    if m:
        near = m.group(2)
        up, down = bool(UP.search(near)), bool(DOWN.search(near))
        if up != down:
            return "up" if up else "down"
    up, down = bool(UP.search(title)), bool(DOWN.search(title))
    return ("up" if up else "down") if up != down else None


_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()
_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True,
                               headers={"User-Agent": "Mozilla/5.0 (DukaanSaathi news reader)"})
    return _client


def _fetch(query: str) -> list[dict]:
    r = _http().get(FEED, params={"q": f"{query} when:{MAX_AGE_DAYS}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        try:
            published = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            published = None
        link = (it.findtext("link") or "").strip()
        if title and link.startswith("https://"):
            out.append({"title": title, "source": source or "News", "link": link, "published": published})
    return out


def _catalogue_words(db: Session, m: Merchant) -> tuple[set[str], set[str]]:
    """(commodities this shop sells, lower-case words from its item names)."""
    names = [n.lower() for (n,) in db.query(Item.name).filter_by(merchant_id=m.id, active=True)]
    words = {w for n in names for w in re.findall(r"[a-z]{4,}", n)}
    comms = {c for c, keys in COMMODITIES.items() if any(re.search(r"\b" + re.escape(k), n) for n in names for k in keys)}
    return comms | SEGMENT_INPUTS.get(m.segment, set()), words


def _raw(segment: str) -> list[dict]:
    """All recent headlines for a business type (cached; on failure, the last good copy)."""
    key = segment if segment in SEGMENT_QUERIES else "other"
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    queries = SEGMENT_QUERIES.get(key, []) + GENERIC
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for res in pool.map(lambda q: _safe_fetch(q), queries):
            items += res
    if not items:
        with _lock:
            return hit[1] if hit else []  # offline: keep showing the last good headlines
    with _lock:
        _cache[key] = (time.time(), items)
    return items


def _safe_fetch(q: str) -> list[dict]:
    try:
        return _fetch(q)
    except Exception as e:  # network / feed format: one query failing must not empty the panel
        log.info("news query failed (%s): %s", q[:40], e)
        return []


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower())[:70]


def for_merchant(db: Session, m: Merchant, limit: int = 6) -> dict:
    comms, words = _catalogue_words(db, m)
    seg_words = {"kirana": {"kirana", "grocery", "fmcg", "retail", "shopkeepers", "retailers"}, "sweets": {"mithai", "sweets", "sweet", "bakery", "dairy"},
                 "salon": {"salon", "beauty", "grooming", "bridal", "wedding", "parlour"}, "pharmacy": {"pharmacy", "chemists", "drug", "medicine"},
                 "restaurant": {"restaurant", "restaurants", "food", "kitchen", "dhaba"}}.get(m.segment, set())
    now = datetime.now(timezone.utc)
    seen, scored = set(), []
    for it in _raw(m.segment):
        title = it["title"]
        k = _norm(title)
        if k in seen or NOISE.search(title) or len(re.sub(r"[\x00-\x7F₹’‘“”–—]", "", title)) > len(title) * 0.2:
            continue  # duplicate, share-market noise, or not in English
        seen.add(k)
        age_days = (now - it["published"]).total_seconds() / 86400 if it["published"] else MAX_AGE_DAYS
        if age_days > MAX_AGE_DAYS:
            continue
        low = title.lower()
        hit_comms = [c for c in sorted(comms) if any(re.search(r"\b" + re.escape(x) + r"s?\b", low) for x in (c, *COMMODITIES[c]))]
        if not BIZ.search(title):
            continue  # not about trade
        score = 3 * len(hit_comms) + 2 * sum(w in low for w in seg_words) + sum(w in low for w in words if len(w) > 4)
        score += 1 if "india" in low or "indian" in low else 0
        score -= age_days / 3  # fresher first
        signal = None
        if hit_comms and re.search(r"\bprice|\bprices|\brates?\b|\bcost", low):
            signal = None
            d = direction(title)
            if d:
                signal = {"commodity": hit_comms[0], "direction": d}
        scored.append((score, {"title": title, "source": it["source"], "link": it["link"],
                               "published": it["published"].isoformat() if it["published"] else None,
                               "age_hours": round(age_days * 24), "topics": hit_comms, "price_signal": signal}))
    scored.sort(key=lambda x: x[0], reverse=True)
    # variety: at most two stories per commodity and per publisher
    picked, per_topic, per_source = [], {}, {}
    for s_, x in scored:
        topics = x["topics"] or ["_general"]
        if any(per_topic.get(t, 0) >= 2 for t in topics) or per_source.get(x["source"], 0) >= 2 or (s_ <= 0 and len(picked) >= 3):
            continue
        for t in topics:
            per_topic[t] = per_topic.get(t, 0) + 1
        per_source[x["source"]] = per_source.get(x["source"], 0) + 1
        picked.append(x)
        if len(picked) >= limit:
            break
    # one signal per commodity: the majority direction across recent headlines, with up to two sources to read
    agg: dict[str, dict] = {}
    for _, x in scored:
        sig = x["price_signal"]
        if not sig:
            continue
        a = agg.setdefault(sig["commodity"], {"commodity": sig["commodity"], "up": 0, "down": 0, "sources": []})
        a[sig["direction"]] += 1
        if len(a["sources"]) < 2:
            a["sources"].append({"title": x["title"], "source": x["source"], "link": x["link"], "published": x["published"]})
    signals = []
    for a in agg.values():
        if a["up"] != a["down"]:
            signals.append({"commodity": a["commodity"], "direction": "up" if a["up"] > a["down"] else "down",
                            "headlines": a["up"] + a["down"], "sources": a["sources"]})
    return {"segment": m.segment, "items": picked, "price_signals": signals, "available": bool(scored),
            "fetched_at": clock.now().isoformat(), "source_note": "Headlines from Google News, linked to the original publisher."}
