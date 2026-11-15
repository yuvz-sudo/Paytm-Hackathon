"""Seasonal stock, pricing and money advice: the "15 years in retail" layer of the Growth Advisor.

Everything numeric is computed here from the shop's own payments, its stock, the festival calendar and real price news.
The LLM (one call a day, cached) only writes the advisor's note from these facts; without it a template note is used.

Demand multipliers are planning rules of thumb for Indian retail (e.g. sugar and ghee sell far more before Diwali,
cold drinks slow down in winter). They are labelled as estimates in the UI."""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import clock, config
from ..languages import NATIVE
from ..models import AdvisorNote, Item, Merchant, Transaction, TxnItem
from ..util import inr
from . import calendar, consent, fees, finance, inventory, ledger, news, settlements

log = logging.getLogger("dukaan.advisor")

HORIZON = 14          # days ahead the stock plan looks at
PREP_DAYS = 5         # festival buying starts this many days before the day itself
TREND_DAYS = 14

# festival -> segment -> {item keyword: demand multiplier in the prep window}
FESTIVAL_DEMAND: dict[str, dict[str, dict[str, float]]] = {
    "Diwali": {"kirana": {"sugar": 1.6, "oil": 1.5, "ghee": 1.8, "atta": 1.3, "dry fruit": 2.0, "besan": 1.5, "cold drink": 1.3, "namkeen": 1.4, "maida": 1.5, "rice": 1.2},
               "sweets": {"kaju": 2.2, "ladoo": 1.8, "dry fruit": 2.5, "ghee": 1.6, "namkeen": 1.6, "gulab": 1.5, "rasgulla": 1.5, "cake": 1.1},
               "salon": {"facial": 1.8, "hair colour": 1.6, "haircut": 1.4, "manicure": 1.5}},
    "Dev Diwali": {"kirana": {"ghee": 1.3, "sugar": 1.2, "oil": 1.2, "atta": 1.1},
                   "sweets": {"ladoo": 1.4, "kaju": 1.3, "gulab": 1.3, "rasgulla": 1.3, "ghee": 1.2}},
    "Christmas": {"kirana": {"cold drink": 1.2, "bread": 1.15, "eggs": 1.3, "maida": 1.3, "sugar": 1.1},
                  "sweets": {"cake": 2.5, "namkeen": 1.2}, "salon": {"facial": 1.3, "haircut": 1.2}},
    "New Year's Eve": {"kirana": {"cold drink": 1.8, "namkeen": 1.6, "maggi": 1.2, "eggs": 1.2},
                       "sweets": {"cake": 1.8, "namkeen": 1.3}, "salon": {"hair colour": 1.4, "facial": 1.5, "haircut": 1.4}},
    "Lohri": {"kirana": {"jaggery": 2.0, "gur": 2.0, "til": 2.5, "peanut": 1.8, "sugar": 1.2, "ghee": 1.2}, "sweets": {"ladoo": 1.5, "gajak": 2.5}},
    "Makar Sankranti": {"kirana": {"jaggery": 2.0, "gur": 2.0, "til": 2.5, "peanut": 1.8, "sugar": 1.2, "ghee": 1.2}, "sweets": {"ladoo": 1.6, "gajak": 2.5}},
    "Valentine's Day": {"sweets": {"cake": 1.8}, "salon": {"facial": 1.4, "haircut": 1.3}},
}
# month -> {keyword: multiplier}; Indian winter and summer
WEATHER = {**{mth: {"chai": 1.15, "tea": 1.15, "milk": 1.1, "eggs": 1.2, "dry fruit": 1.15, "jaggery": 1.2, "cold drink": 0.75, "ice cream": 0.6} for mth in (11, 12, 1, 2)},
           **{mth: {"cold drink": 1.5, "ice cream": 1.8, "chai": 0.9, "tea": 0.9} for mth in (4, 5, 6)}}
WEATHER_NAME = {11: "winter", 12: "winter", 1: "winter", 2: "winter", 4: "summer", 5: "summer", 6: "summer"}
# approximate wedding-season windows (muhurat dates vary by year)
WEDDING = [((11, 20), (12, 15)), ((1, 15), (2, 28))]
WEDDING_DEMAND = {"sweets": {"dry fruit": 1.4, "kaju": 1.3, "ladoo": 1.2}, "salon": {"bridal": 2.0, "facial": 1.3, "hair colour": 1.2},
                  "kirana": {"oil": 1.1, "sugar": 1.1, "rice": 1.1}}
# item keyword -> commodity name used by price news
ITEM_COMMODITY = {"sugar": "sugar", "atta": "wheat", "oil": "edible oil", "dal": "pulses", "rice": "rice", "milk": "milk", "ghee": "ghee",
                  "dry fruit": "dry fruits", "kaju": "dry fruits", "egg": "eggs", "salt": "salt", "turmeric": "spices", "chai": "tea"}


def _in_wedding(d: date) -> bool:
    return any((a <= (d.month, d.day) <= b) for a, b in WEDDING)


def _kw(name: str, table: dict[str, float]) -> float:
    n = name.lower()
    hits = [v for k, v in table.items() if k in n]
    return max(hits, key=lambda v: abs(v - 1)) if hits else 1.0


def _festival_dates(seg: str, today: date, within: int = 30) -> list[dict]:
    out = []
    for f in calendar.upcoming(seg, within):
        out.append({**f, "date_obj": date.fromisoformat(f["date"])})
    return out


def day_multiplier(item: str, seg: str, d: date, fests: list[dict]) -> tuple[float, str | None]:
    """Demand multiplier for one item on one day, and the reason that moves it most."""
    parts: list[tuple[float, str]] = []
    w = _kw(item, WEATHER.get(d.month, {}))
    if w != 1.0:
        parts.append((w, WEATHER_NAME.get(d.month, "season")))
    if _in_wedding(d):
        wd = _kw(item, WEDDING_DEMAND.get(seg, {}))
        if wd > 1.0:
            parts.append((wd, "wedding season"))
    for f in fests:
        if 0 <= (f["date_obj"] - d).days <= PREP_DAYS:
            fm = _kw(item, FESTIVAL_DEMAND.get(f["name"], {}).get(seg, {}))
            if fm > 1.0:
                parts.append((fm, f["name"]))
    mult = 1.0
    for x, _ in parts:
        mult *= x
    why = max(parts, key=lambda p: abs(math.log(p[0])))[1] if parts else None
    return mult, why


def _pace(db: Session, mid: int, start: datetime, end: datetime) -> dict[int, tuple[float, float]]:
    """item_id -> (qty, revenue) of successful itemised sales in [start, end)."""
    rows = (db.query(TxnItem.item_id, TxnItem.qty, TxnItem.amount).join(Transaction, Transaction.id == TxnItem.txn_id)
            .filter(Transaction.merchant_id == mid, Transaction.status == "success", Transaction.ts >= start, Transaction.ts < end).all())
    out: dict[int, list[float]] = {}
    for iid, q, a in rows:
        x = out.setdefault(iid, [0.0, 0.0])
        x[0] += q
        x[1] += a
    return {k: (v[0], v[1]) for k, v in out.items()}


def season(m: Merchant) -> dict:
    today = clock.today()
    fests = [{k: v for k, v in f.items() if k != "date_obj"} for f in _festival_dates(m.segment, today, 30)]
    return {"today": today.isoformat(), "weather": WEATHER_NAME.get(today.month, "regular season"), "wedding_season": _in_wedding(today),
            "festivals": fests}


def plan(db: Session, m: Merchant, with_news: bool = True) -> dict:
    """The full advice: season, stock moves, slow sellers to discount, money advice, and price signals from the news."""
    today = clock.today()
    now = clock.now()
    seg = m.segment
    fests = _festival_dates(seg, today, 30)
    sig_by_comm: dict[str, dict] = {}
    price_signals: list[dict] = []
    if with_news:
        try:
            nw = news.for_merchant(db, m)
            price_signals = nw["price_signals"]
            sig_by_comm = {s["commodity"]: s for s in price_signals}
        except Exception as e:  # news is a bonus; advice works without it
            log.info("news unavailable for advice: %s", e)
    out: dict = {"season": season(m), "stock_moves": [], "slow_sellers": [], "service_moves": [], "money": [], "price_signals": price_signals,
                 "no_data": False, "generated_at": now.isoformat(), "max_discount_pct": m.max_offer_discount_pct}
    if not consent.is_granted(db, m.id, "transactions"):
        out["blocked"] = ["transactions"]
        return out

    items = db.query(Item).filter_by(merchant_id=m.id, active=True).all()
    t0 = datetime.combine(today, datetime.min.time())
    recent = _pace(db, m.id, t0 - timedelta(days=TREND_DAYS), t0)
    before = _pace(db, m.id, t0 - timedelta(days=TREND_DAYS + 28), t0 - timedelta(days=TREND_DAYS))
    if not recent and not before:
        out["no_data"] = True
        return out
    stock = {r["item_id"]: r for r in inventory.stock_status(db, m)["items"]}
    days = [today + timedelta(days=i) for i in range(1, HORIZON + 1)]

    for it in items:
        q14, rev14 = recent.get(it.id, (0.0, 0.0))
        q28, _ = before.get(it.id, (0.0, 0.0))
        pace = q14 / TREND_DAYS
        prev_pace = q28 / 28
        mults = [day_multiplier(it.name, seg, d, fests) for d in days]
        uplift = sum(x for x, _ in mults) / HORIZON
        reasons = [w for _, w in mults if w]
        reason = max(set(reasons), key=reasons.count) if reasons else None
        comm = next((c for k, c in ITEM_COMMODITY.items() if k in it.name.lower()), None)
        sig = sig_by_comm.get(comm) if comm else None

        if not it.track_stock:  # services and made-to-order items: plan capacity, not stock
            if it.unit == "service" and uplift >= 1.15 and pace > 0:
                out["service_moves"].append({"item": it.name, "uplift_pct": round((uplift - 1) * 100), "reason": reason,
                                             "extra_per_day": round(pace * (uplift - 1), 1),
                                             "advice": f"Expect about {round((uplift - 1) * 100)}% more {it.name.lower()} bookings"
                                                       f"{' because of ' + reason if reason else ''}. Open extra slots and plan staff early."})
            continue

        st = stock.get(it.id, {})
        cur = st.get("current_stock")
        lead = (st.get("supplier") or {}).get("lead_time_days") or 2
        expected = pace * HORIZON * uplift
        unit = it.unit if it.unit not in ("pc",) else "pcs"
        if pace > 0 and uplift >= 1.12:
            need = expected + pace * uplift * lead - (cur or 0)
            pack = it.pack_qty or 1
            if cur is None:
                out["stock_moves"].append({"item": it.name, "move": "check", "uplift_pct": round((uplift - 1) * 100), "reason": reason,
                                           "advice": f"Demand for {it.name} usually rises about {round((uplift - 1) * 100)}%"
                                                     f"{' around ' + reason if reason else ''}. Count what you have so Saathi can size the order.",
                                           "price_signal": sig})
            elif need > 0:
                qty = max(pack, math.ceil(need / pack) * pack)
                first = min((f["date_obj"] for f in fests if f["name"] == reason), default=None)
                by = (first - timedelta(days=PREP_DAYS + lead)) if first else today + timedelta(days=max(1, (st.get("days_left") or lead) - lead))
                by = max(by, today)
                adv = f"Stock up on {it.name}: about {qty:g} {unit} more by {by.strftime('%d %b')}" + \
                      (f" — {reason} usually lifts it ~{round((uplift - 1) * 100)}%." if reason else ".")
                if sig and sig["direction"] == "up":
                    adv += f" {comm.title()} prices are rising in the news, so buying this week is cheaper than later."
                elif sig and sig["direction"] == "down":
                    adv += f" {comm.title()} prices are easing, so buy in two lots rather than all at once."
                out["stock_moves"].append({"item": it.name, "move": "increase", "qty": qty, "unit": unit, "by": by.isoformat(),
                                           "uplift_pct": round((uplift - 1) * 100), "reason": reason, "current_stock": cur,
                                           "expected_14d": round(expected, 1), "est_cost": round(qty * it.price * 0.85),
                                           "advice": adv, "price_signal": sig})
        elif pace > 0 and cur is not None:
            days_left = cur / (pace * uplift) if pace * uplift else None
            if uplift <= 0.88 and days_left and days_left > HORIZON:
                out["stock_moves"].append({"item": it.name, "move": "reduce", "uplift_pct": round((uplift - 1) * 100), "reason": reason,
                                           "days_cover": round(days_left), "current_stock": cur,
                                           "advice": f"Go slow on {it.name}: demand is about {round((1 - uplift) * 100)}% lower in {reason or 'this season'}"
                                                     f" and you already have ~{round(days_left)} days of stock. Skip the next re-order."})
            elif days_left and days_left > max(30, 4 * ((it.cover_days or 7) + lead)):
                out["stock_moves"].append({"item": it.name, "move": "reduce", "uplift_pct": round((uplift - 1) * 100), "reason": None,
                                           "days_cover": round(days_left), "current_stock": cur,
                                           "advice": f"You hold about {round(days_left)} days of {it.name}. Hold re-orders until it falls below "
                                                     f"{(it.cover_days or 7) + lead} days; that frees cash."})

        # slow sellers: sales fell well below their usual pace and stock is sitting on the shelf
        cover_now = (cur / pace) if (cur and pace) else None
        declining = prev_pace >= 0.4 and pace < 0.7 * prev_pace
        sitting = cover_now is not None and cover_now > 25 and pace > 0
        if (declining or sitting) and uplift < 1.12:
            drop = round((1 - pace / prev_pace) * 100) if prev_pace and pace < prev_pace else 0
            cap = max(0, m.max_offer_discount_pct or 0)
            pct = min(cap, 10 if drop < 50 else 15)
            cover = round(cur / pace) if cur and pace else None
            if pct > 0 and (cur is None or cur > pace * 7) and not (cover_now and cover_now < 10 and not declining):
                why_slow = (f"{it.name} sales are down {drop}% (from {prev_pace:.1f} to {pace:.1f} a day)" + (f" with ~{cover} days of stock" if cover else "")
                            if declining else f"{it.name} is moving slowly: ~{cover} days of stock at {pace:.1f} a day")
                out["slow_sellers"].append({"item": it.name, "drop_pct": drop, "was_per_day": round(prev_pace, 1), "now_per_day": round(pace, 1),
                                            "days_cover": cover, "discount_pct": pct, "why": "declining" if declining else "overstocked",
                                            "advice": why_slow + f". Try {pct}% off for a week, or bundle it with a best seller."})

    out["stock_moves"].sort(key=lambda x: ({"increase": 0, "check": 1, "reduce": 2}[x["move"]], -abs(x.get("uplift_pct") or 0)))
    if not out["slow_sellers"]:
        # nothing is falling: still help the weakest products (lowest revenue, not in a seasonal upswing)
        cands = []
        for it in items:
            q14, rev14 = recent.get(it.id, (0.0, 0.0))
            if not it.track_stock or q14 <= 0:
                continue
            up = sum(day_multiplier(it.name, seg, d, fests)[0] for d in days) / HORIZON
            if up < 1.05:
                cands.append((rev14, it, q14 / TREND_DAYS))
        cands.sort(key=lambda c: c[0])
        total = sum(c[0] for c in cands) or 1
        pct = min(max(0, m.max_offer_discount_pct or 0), 5)
        for rev14, it, pace in cands[:2]:
            if rev14 / total > 0.06:
                break  # not really weak
            out["slow_sellers"].append({"item": it.name, "drop_pct": 0, "was_per_day": round(pace, 1), "now_per_day": round(pace, 1),
                                        "days_cover": None, "discount_pct": pct, "why": "lowest_seller",
                                        "advice": f"{it.name} is one of your weakest sellers ({inr(rev14)} in 14 days, {rev14 / total * 100:.0f}% of item sales). "
                                                  + (f"Bundle it with a best seller or try {pct}% off for a week." if pct else "Bundle it with a best seller or keep it near the counter.")})
    out["slow_sellers"].sort(key=lambda x: (-x["drop_pct"], -(x["days_cover"] or 0)))
    out["slow_sellers"] = out["slow_sellers"][:4]
    slow_names = {x["item"] for x in out["slow_sellers"]}
    out["stock_moves"] = [x for x in out["stock_moves"] if not (x["move"] == "reduce" and x["item"] in slow_names and x["reason"] is None)]
    out["money"] = money(db, m, out)
    return out


def money(db: Session, m: Merchant, p: dict) -> list[dict]:
    """Financial advice with the numbers behind it."""
    tips: list[dict] = []
    fc = finance.forecast(db, m)
    buy = sum(x.get("est_cost") or 0 for x in p["stock_moves"] if x["move"] == "increase")
    if not fc.get("no_data"):
        likely = fc["collections"]["likely"]
        trend = fc.get("trend_pct")
        if fc.get("crunch"):
            c = fc["crunch"]
            tips.append({"id": "cash_gap", "tone": "bad", "title": "Cash will be tight",
                         "detail": f"Bills due by {c.get('date', 'soon')} are larger than the money expected in. Keep {inr(c.get('shortfall') or 0)} aside, "
                                   "collect overdue udhaar first, and delay non-urgent purchases."})
        else:
            tips.append({"id": "cash_ok", "tone": "good", "title": "Cash flow looks healthy",
                         "detail": f"About {inr(likely)} should come in over the next 30 days against {inr(fc['bills_total'])} of known bills. "
                                   "Keep at least two weeks of expenses as a buffer before buying in bulk."})
        if buy:
            share = buy / likely * 100 if likely else 100
            tight = bool(fc.get("crunch")) or share > 25
            tips.append({"id": "festival_buy", "tone": "warn" if tight else "good", "title": "Festival stock budget",
                         "detail": f"The extra stock suggested here costs roughly {inr(buy)} (estimated at 85% of selling price), "
                                   f"about {share:.0f}% of next month's expected collections. "
                                   + ("Because cash is tight, buy only the top two items now and the rest after collections come in."
                                      if fc.get("crunch") else "Split the purchase across two orders." if share > 25 else "That is comfortably affordable.")})
        if trend is not None and abs(trend) >= 5:
            tips.append({"id": "trend", "tone": "good" if trend > 0 else "warn", "title": f"Sales trend {'up' if trend > 0 else 'down'} {abs(trend):.0f}%",
                         "detail": "Recent weeks are stronger than before. Lock in supplier rates now while volumes are high." if trend > 0 else
                                   "Recent weeks are weaker. Trim slow stock, keep orders small and push your best sellers."})
    if consent.is_granted(db, m.id, "ledger"):
        d = ledger.dues(db, m)
        month_sales = (fc.get("collections") or {}).get("likely") or 0
        if d["total_overdue"] and month_sales:
            share = d["total_overdue"] / month_sales * 100
            tips.append({"id": "udhaar", "tone": "warn" if share > 3 else "good", "title": "Udhaar is tying up cash" if share > 3 else "Udhaar is under control",
                         "detail": f"{inr(d['total_overdue'])} of udhaar is overdue ({share:.1f}% of a month's sales). "
                                   + ("Collect before giving new credit, and cap credit per customer." if share > 3 else "Keep reminding gently.")})
    stl = settlements.status(db, m)
    if stl.get("stuck_amount"):
        tips.append({"id": "stuck", "tone": "bad", "title": "Money stuck in settlements",
                     "detail": f"{inr(stl['stuck_amount'])} has not reached your bank. Fix bank details or raise it with Paytm support today."})
    try:
        mdr = fees.mdr_estimate(db, m, "this_month")
        if mdr.get("estimated_mdr"):
            tips.append({"id": "mdr", "tone": "warn", "title": "UPI fee this month",
                         "detail": f"An estimated {inr(mdr['estimated_mdr'])} in UPI fees this month. Encourage smaller customers to pay by QR "
                                   "and keep large B2B payments on bank transfer."})
    except Exception:
        pass
    tips.sort(key=lambda t: {"bad": 0, "warn": 1, "good": 2}[t["tone"]])  # problems first
    return tips


# ---------------------------------------------------------------- the advisor's note (LLM once a day, cached)

PROMPT = """You are Saathi, a warm, respectful business and financial advisor with 15 years of experience helping small Indian shops
({segment}). Write today's note for {owner} of "{shop}" in {city}.

Rules:
- Use ONLY the facts in the JSON. Never invent prices, numbers, dates or news. Quote the source when you mention news.
- 4 to 6 short bullet points, most important first, each starting with "• ". Plain words, no jargon, no markdown headings.
- Be specific: item, quantity, date, rupees. Mention festival / season timing where relevant.
- If a discount is suggested, keep it within {max_discount}% and say it needs their approval.
- End with one encouraging line.
- Language: {language}.

Facts:
{facts}"""
LANG_NAME = {"en": "simple English", "hi": "Hindi in Devanagari script", "hinglish": "Hinglish (Hindi in Roman script, mixed with English)"}


def _facts(p: dict) -> str:
    keep = {"season": p["season"], "stock_moves": [{k: v for k, v in x.items() if k in ("item", "move", "qty", "unit", "by", "uplift_pct", "reason", "advice")}
                                                   for x in p["stock_moves"][:6]],
            "slow_sellers": [{k: x[k] for k in ("item", "drop_pct", "discount_pct", "days_cover")} for x in p["slow_sellers"][:3]],
            "service_moves": p["service_moves"][:3], "money": [{"title": x["title"], "detail": x["detail"]} for x in p["money"][:4]],
            "price_news": [{"commodity": s["commodity"], "direction": s["direction"], "source": s["sources"][0]["source"] if s.get("sources") else None}
                           for s in p["price_signals"][:4]]}
    return json.dumps(keep, ensure_ascii=False, default=str)


def template_note(m: Merchant, p: dict) -> str:
    first = (m.owner_name or "").split()[0] if m.owner_name else ""
    lines = [f"Namaste {first} ji, here is my advice for the coming two weeks." if first else "Here is my advice for the coming two weeks."]
    for f in p["season"]["festivals"][:1]:
        lines.append(f"• {f['name']} is {f['days']} days away. {f['hint']}")
    for x in [x for x in p["stock_moves"] if x["move"] == "increase"][:2]:
        lines.append("• " + x["advice"])
    for x in p["service_moves"][:1]:
        lines.append("• " + x["advice"])
    for x in [x for x in p["stock_moves"] if x["move"] == "reduce"][:1]:
        lines.append("• " + x["advice"])
    for x in p["slow_sellers"][:1]:
        lines.append("• " + x["advice"] + " (only after your approval)")
    for x in [t for t in p["money"] if t["tone"] != "good"][:1] or p["money"][:1]:
        lines.append(f"• {x['title']}: {x['detail']}")
    lines.append("Small, steady steps every week add up. I am here whenever you want to talk it through.")
    return "\n".join(lines)


def note(db: Session, m: Merchant, p: dict, refresh: bool = False) -> dict:
    """{'text', 'source': 'llm'|'template', 'language'} — at most one LLM call per merchant per day (and per language)."""
    from ..agent import llm
    from . import sarvam
    today = clock.today()
    lang = m.language or "en"
    row = db.query(AdvisorNote).filter_by(merchant_id=m.id, for_date=today, language=lang).first()
    if row and not refresh:
        return {"text": row.text, "source": row.source, "language": lang, "cached": True}
    if row and refresh and row.source == "llm":
        return {"text": row.text, "source": row.source, "language": lang, "cached": True}  # one paid note a day is enough
    write_lang = lang if lang in LANG_NAME else "en"
    text, source = None, "template"
    if p["stock_moves"] or p["slow_sellers"] or p["money"] or p["service_moves"]:
        prompt = PROMPT.format(segment=m.segment, owner=m.owner_name or "the owner", shop=m.name, city=m.city or "India",
                               max_discount=m.max_offer_discount_pct, language=LANG_NAME[write_lang], facts=_facts(p))
        text = llm.write_copy(db, m.id, prompt, kind="advisor", max_tokens=420)
        source = "llm" if text else "template"
    if not text:
        text = template_note(m, p)
    if lang in NATIVE:
        try:
            text = sarvam.translate(db, text, lang, merchant_id=m.id)
        except Exception:
            db.rollback()
    if row:
        row.text, row.source, row.created_at = text, source, clock.now()
    else:
        db.add(AdvisorNote(merchant_id=m.id, for_date=today, language=lang, text=text, source=source, created_at=clock.now()))
    db.commit()
    return {"text": text, "source": source, "language": lang, "cached": False}
