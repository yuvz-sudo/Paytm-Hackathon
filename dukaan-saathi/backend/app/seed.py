"""Deterministic demo data generator.

Three merchant segments so the product is exercised beyond a kirana store:
  1. Ramesh Kirana Store (Pune)      - stock heavy, udhaar heavy, Hinglish
  2. Sharma Sweets & Bakery (Jaipur) - festival driven, cash-flow gap, Hindi
  3. Glow Unisex Salon (Bengaluru)   - services only (no stock), English

Everything is relative to "today" so the demo never goes stale. Data deliberately contains
messy cases: failed payments, refunds, un-itemised sales, a delayed and a failed settlement,
overdue udhaar, lapsed regulars and a post-festival sales dip.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import clock
from .db import Base, engine
from .models import (
    Chargeback, Consent, Customer, Item, LedgerEntry, Merchant, Payable, Review, Settlement, SettlementLine, Supplier, Transaction,
    TxnItem,
)

CONSENT_SCOPES = ["transactions", "customers", "ledger", "credit", "messaging"]
HISTORY_DAYS = 75
# perishables: order only a couple of days of sales at a time
PERISHABLE_COVER = {"Amul Milk 500ml": 2, "Bread": 2, "Eggs (tray)": 4, "Cake (500g)": 2, "Samosa": 1, "Kachori": 1}

FIRST = ["Aarav", "Vivaan", "Sunita", "Meena", "Rohit", "Priya", "Anil", "Kavita", "Suresh", "Neha", "Imran", "Farah",
         "Deepak", "Pooja", "Manoj", "Lata", "Ravi", "Geeta", "Sanjay", "Anita", "Vikram", "Shobha", "Arjun", "Ritu",
         "Harish", "Usha", "Nitin", "Seema", "Kiran", "Mohan", "Asha", "Gopal", "Rekha", "Dinesh", "Jyoti", "Pankaj"]
LAST = ["Sharma", "Patil", "Deshmukh", "Verma", "Khan", "Gupta", "Joshi", "Iyer", "Singh", "Kulkarni", "Yadav", "Naik",
        "Mehta", "Reddy", "Jain", "Pawar", "Shah", "Rao"]

# name, aliases, unit, price, gst, base units/day, pack, tracked, supplier idx
KIRANA_ITEMS = [
    ("Chai (cup)", ["chai", "tea", "चाय"], "cup", 10, 5, 62, 1, False, None),
    ("Atta 5kg", ["atta", "aata", "flour", "आटा"], "bag", 235, 0, 6.5, 10, True, 0),
    ("Sugar", ["sugar", "cheeni", "chini", "चीनी", "शक्कर"], "kg", 46, 5, 14, 25, True, 0),
    ("Toor Dal", ["dal", "toor", "arhar", "दाल"], "kg", 148, 0, 5, 10, True, 0),
    ("Rice (Basmati)", ["rice", "chawal", "चावल"], "kg", 92, 5, 7, 25, True, 0),
    ("Amul Milk 500ml", ["milk", "doodh", "दूध"], "pc", 29, 0, 38, 24, True, 1),
    ("Parle-G", ["parle", "biscuit", "बिस्कुट"], "pc", 10, 18, 30, 48, True, 2),
    ("Maggi Noodles", ["maggi", "noodles", "मैगी"], "pc", 14, 12, 20, 48, True, 2),
    ("Tata Salt 1kg", ["salt", "namak", "नमक"], "pc", 28, 0, 5, 20, True, 0),
    ("Sunflower Oil 1L", ["oil", "tel", "तेल"], "pc", 142, 5, 5, 12, True, 0),
    ("Turmeric Powder", ["haldi", "turmeric", "हल्दी"], "pc", 62, 5, 2.5, 20, True, 0),
    ("Bread", ["bread", "pav", "ब्रेड"], "pc", 42, 0, 14, 12, True, 1),
    ("Eggs (tray)", ["egg", "eggs", "anda", "अंडे"], "tray", 190, 0, 1.6, 6, True, 1),
    ("Cold Drink 600ml", ["cold drink", "coke", "thums up", "कोल्ड ड्रिंक"], "pc", 40, 28, 13, 24, True, 2),
    ("Soap (Lux)", ["soap", "sabun", "साबुन"], "pc", 35, 18, 6, 36, True, 2),
    ("Detergent 1kg", ["detergent", "surf", "washing powder"], "pc", 128, 18, 2.6, 12, True, 2),
]

SWEETS_ITEMS = [
    ("Kaju Katli (kg)", ["kaju katli", "kaju", "काजू कतली"], "kg", 900, 5, 6.0, 5, True, 0),
    ("Gulab Jamun (kg)", ["gulab jamun", "jamun", "गुलाब जामुन"], "kg", 380, 5, 9.0, 5, True, 0),
    ("Rasgulla (kg)", ["rasgulla", "रसगुल्ला"], "kg", 360, 5, 5.0, 5, True, 0),
    ("Samosa", ["samosa", "समोसा"], "pc", 15, 5, 85, 1, False, None),
    ("Kachori", ["kachori", "कचौरी"], "pc", 20, 5, 70, 1, False, None),
    ("Besan Ladoo (kg)", ["ladoo", "laddu", "besan", "लड्डू"], "kg", 420, 5, 7.0, 5, True, 0),
    ("Cake (500g)", ["cake", "केक"], "pc", 520, 18, 4.0, 3, True, 1),
    ("Namkeen Mix (kg)", ["namkeen", "mixture", "नमकीन"], "kg", 260, 12, 6.0, 5, True, 0),
    ("Ghee (1kg)", ["ghee", "घी"], "pc", 640, 12, 2.0, 6, True, 2),
    ("Dry Fruit Box", ["dry fruit", "box", "gift box"], "pc", 750, 12, 2.5, 4, True, 0),
]

SALON_ITEMS = [
    ("Haircut", ["haircut", "cut"], "service", 350, 18, 5.0, 1, False, None),
    ("Hair Colour", ["colour", "color"], "service", 1800, 18, 1.0, 1, False, None),
    ("Facial", ["facial"], "service", 1200, 18, 1.6, 1, False, None),
    ("Manicure", ["manicure"], "service", 700, 18, 1.2, 1, False, None),
    ("Beard Trim", ["beard", "shave"], "service", 150, 18, 3.5, 1, False, None),
    ("Bridal Package", ["bridal"], "service", 12000, 18, 0.01, 1, False, None),
]

SUPPLIERS = {
    "kirana": [("Gupta Wholesale", "+91 98200 11111", 2, "hinglish"), ("Patil Dairy", "+91 98200 22222", 1, "hinglish"),
               ("Metro FMCG Distributors", "+91 98200 33333", 3, "en")],
    "sweets": [("Jaipur Mawa Traders", "+91 98290 11111", 2, "hi"), ("Sharma Bakers Supply", "+91 98290 22222", 2, "hi"),
               ("Rajasthan Ghee House", "+91 98290 33333", 3, "hi")],
    "salon": [],
}

MERCHANTS = [
    dict(key="kirana", phone="+919876500001", name="Ramesh Kirana Store", owner="Ramesh", segment="kirana", city="Pune", lang="hinglish",
         gst=True, soundbox="PSB-4471", items=KIRANA_ITEMS, daily=105, hours=(7, 22), seed=11, itemized=0.82,
         avg_untemized=(60, 420), ncust=70),
    dict(key="sweets", phone="+919876500002", name="Sharma Sweets & Bakery", owner="Anil Sharma", segment="sweets", city="Jaipur", lang="hi",
         gst=True, soundbox="PSB-5120", items=SWEETS_ITEMS, daily=64, hours=(9, 21), seed=22, itemized=0.7,
         avg_untemized=(120, 1500), ncust=45),
    dict(key="salon", phone="+919876500003", name="Glow Unisex Salon", owner="Pooja Nair", segment="salon", city="Bengaluru", lang="en",
         gst=False, soundbox="PSB-6008", items=SALON_ITEMS, daily=7, hours=(10, 20), seed=33, itemized=0.9,
         avg_untemized=(250, 1200), ncust=40),
]


def _hour_weights(segment: str, lo: int, hi: int) -> dict[int, float]:
    w = {}
    for h in range(lo, hi):
        if segment == "kirana":
            w[h] = 3.0 if h in (8, 9, 10) else 2.6 if h in (18, 19, 20) else 1.2 if h in (14, 15) else 1.6
        elif segment == "sweets":
            w[h] = 3.0 if h in (11, 12, 17, 18, 19) else 0.7 if h in (14, 15) else 1.5
        else:
            w[h] = 2.5 if h in (11, 12, 16, 17, 18) else 1.0
    return w


def _weekday_factor(segment: str, d: date) -> float:
    wd = d.weekday()  # 0 Mon
    if segment == "salon":
        return {0: 0.7, 1: 0.8, 2: 0.9, 3: 1.0, 4: 1.15, 5: 1.5, 6: 1.4}[wd]
    return {0: 0.95, 1: 0.92, 2: 0.95, 3: 1.0, 4: 1.08, 5: 1.18, 6: 1.1}[wd]


def _festival_factor(segment: str, d: date, today: date) -> float:
    """Sweets ramp up the week before Diwali and dip right after. Anchored to 8 Nov 2026."""
    if segment != "sweets":
        return 1.0
    diwali = date(2026, 11, 8)
    delta = (d - diwali).days
    if -7 <= delta <= 0:
        return 1.0 + (7 + delta) * 0.22  # ramps to ~2.5x
    if 1 <= delta <= 5:
        return 0.55
    return 1.0


def reset_db() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _pick_items(rng: random.Random, items: list[Item], weights: list[float], segment: str):
    n = rng.choices([1, 2, 3, 4, 5], weights=[30, 32, 22, 10, 6] if segment == "kirana" else [55, 30, 10, 4, 1])[0]
    chosen = set()
    out = []
    for _ in range(n * 3):
        it = rng.choices(items, weights=weights)[0]
        if it.id in chosen:
            continue
        chosen.add(it.id)
        if it.unit == "kg":
            qty = rng.choice([0.25, 0.5, 1, 1, 2])
        elif it.unit == "cup":
            qty = rng.choice([1, 1, 2, 3])
        elif it.unit == "service":
            qty = 1
        elif it.pack_qty >= 20:
            qty = rng.choice([1, 1, 2, 3, 4])
        else:
            qty = rng.choice([1, 1, 1, 2])
        out.append((it, qty))
        if len(out) == n:
            break
    return out


def populate(db: Session, m: Merchant, spec: dict, now: datetime | None = None) -> None:
    """Create suppliers, catalogue, customers, 75 days of payments, ledger, reviews, settlements and bills
    for a merchant. Used for the demo merchants and for new merchants who choose 'explore with sample data'."""
    now = now or clock.now()
    today = now.date()
    rng = random.Random(spec["seed"])
    sups = []
    for name, phone, lead, lang in SUPPLIERS[spec["segment"]]:
        s = Supplier(merchant_id=m.id, name=name, phone=phone, lead_time_days=lead, language=lang)
        db.add(s)
        sups.append(s)
    db.flush()

    items: list[Item] = []
    for name, aliases, unit, price, gst, base, pack, tracked, sidx in spec["items"]:
        it = Item(merchant_id=m.id, name=name, aliases=aliases, unit=unit, price=price, gst_rate=gst,
                  track_stock=tracked, pack_qty=pack, cover_days=PERISHABLE_COVER.get(name, 7), supplier_id=sups[sidx].id if sidx is not None else None)
        db.add(it)
        items.append(it)
    db.flush()
    base_rate = {it.id: spec["items"][i][5] for i, it in enumerate(items)}

    # Customers: zipf-ish loyalty; some lapse (stop visiting) to create win-back opportunities.
    custs: list[Customer] = []
    lapse_after: dict[int, date | None] = {}
    for i in range(spec["ncust"]):
        nm = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        c = Customer(merchant_id=m.id, name=nm, phone=f"+91 9{rng.randint(100000000, 999999999)}",
                     created_at=now - timedelta(days=rng.randint(30, 400)))
        db.add(c)
        custs.append(c)
    db.flush()
    cust_w = [1.0 / (i + 1) ** 0.8 for i in range(len(custs))]
    for i, c in enumerate(custs):
        lapse_after[c.id] = None
        if 3 <= i < 3 + max(6, len(custs) // 8):  # loyal-ish customers that vanished
            lapse_after[c.id] = today - timedelta(days=rng.randint(18, 45))

    hw = _hour_weights(spec["segment"], *spec["hours"])
    hours = list(hw.keys())
    hweights = list(hw.values())
    item_w = [base_rate[it.id] * (it.price if it.unit == "service" else 1) ** 0.0 for it in items]
    if spec["segment"] != "salon":
        item_w = [base_rate[it.id] for it in items]
    else:
        item_w = [base_rate[it.id] for it in items]

    for back in range(HISTORY_DAYS, -1, -1):
        d = today - timedelta(days=back)
        f = _weekday_factor(spec["segment"], d) * _festival_factor(spec["segment"], d, today)
        n = max(0, int(rng.gauss(spec["daily"] * f, spec["daily"] * 0.07)))
        if spec["segment"] == "salon" and d.weekday() == 0:
            n = int(n * 0.9)
        for _ in range(n):
            h = rng.choices(hours, weights=hweights)[0]
            ts = datetime(d.year, d.month, d.day, h, rng.randint(0, 59), rng.randint(0, 59))
            if ts > now:  # never create future payments for "today"
                continue
            cust = None
            if rng.random() < 0.38:
                c = rng.choices(custs, weights=cust_w)[0]
                la = lapse_after[c.id]
                if la is None or d <= la:
                    cust = c
            roll = rng.random()
            status = "failed" if roll < 0.025 else "refunded" if roll < 0.033 else "success"
            mode = rng.choices(["UPI", "CARD", "WALLET"], weights=[88, 7, 5])[0]
            itemized = rng.random() < spec["itemized"]
            t = Transaction(merchant_id=m.id, customer_id=cust.id if cust else None, ts=ts, status=status,
                            mode=mode, itemized=itemized, amount=0)
            if itemized:
                total = 0.0
                for it, qty in _pick_items(rng, items, item_w, spec["segment"]):
                    amt = round(it.price * qty, 2)
                    total += amt
                    t.items.append(TxnItem(item_id=it.id, qty=qty, amount=amt))
                t.amount = round(total, 2)
            else:
                lo_, hi_ = spec["avg_untemized"]
                t.amount = float(round(rng.uniform(lo_, hi_) / 5) * 5)
            db.add(t)
        if back % 10 == 0:
            db.flush()
    db.flush()

    _seed_stock(db, m, items, base_rate, spec, now)
    _seed_ledger(db, m, custs, rng, today, now)
    _seed_settlements(db, m, rng, today)
    _seed_chargebacks(db, m, today)
    _seed_payables(db, m, sups, spec["segment"], today)
    db.flush()


def seed(db: Session, reset: bool = True) -> list[int]:
    if reset:
        reset_db()
    now = clock.now()
    today = now.date()
    ids = []
    for spec in MERCHANTS:
        rng = random.Random(spec["seed"])
        m = Merchant(
            name=spec["name"], owner_name=spec["owner"], segment=spec["segment"], city=spec["city"],
            language=spec["lang"], phone=spec["phone"], gst_registered=spec["gst"], onboarded=True, sample_data=True,
            soundbox_id=spec["soundbox"],
        )
        db.add(m)
        db.flush()
        ids.append(m.id)
        for scope in CONSENT_SCOPES:
            db.add(Consent(merchant_id=m.id, scope=scope, granted=True, updated_at=now))
        populate(db, m, spec, now)
        db.commit()
    return ids


def _seed_stock(db, m, items, base_rate, spec, now):
    if spec["segment"] == "salon":
        return
    reported_at = datetime(now.year, now.month, now.day) - timedelta(days=3) + timedelta(hours=20)
    rng = random.Random(spec["seed"] + 1)
    targets = {"Atta 5kg": 2.1, "Sugar": 1.8, "Kaju Katli (kg)": 2.5, "Cake (500g)": 1.4, "Amul Milk 500ml": 0.8}
    for it in items:
        if not it.track_stock:
            continue
        sold = (
            db.query(TxnItem).join(Transaction, Transaction.id == TxnItem.txn_id)
            .filter(TxnItem.item_id == it.id, Transaction.ts >= reported_at, Transaction.status == "success")
            .with_entities(TxnItem.qty).all()
        )
        sold_qty = sum(q for (q,) in sold)
        days_left = targets.get(it.name, rng.uniform(5, 16))
        # estimator scales itemised sales by 1/itemisation-rate, so mirror that to land near the target days left
        it.stock_qty = round(sold_qty / spec["itemized"] + days_left * base_rate[it.id] * 0.9, 1)
        it.stock_reported_at = reported_at
    # one item the owner never reported stock for: exercises the "unknown stock" path
    for it in items:
        if it.track_stock and it.name in ("Detergent 1kg", "Turmeric Powder"):
            it.stock_qty = None
            it.stock_reported_at = None


def _seed_ledger(db, m, custs, rng, today, now):
    if m.segment == "salon":
        picks = custs[:3]
    else:
        picks = custs[:14]
    for i, c in enumerate(picks):
        k = rng.randint(1, 3)
        total_credit = 0.0
        for _ in range(k):
            age = rng.choice([3, 8, 15, 26, 41, 63])
            amt = float(rng.choice([150, 240, 320, 500, 780, 1200, 1850]))
            ts = now - timedelta(days=age)
            db.add(LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="credit_given", amount=amt, ts=ts,
                               due_date=(ts + timedelta(days=15)).date(), note="udhaar"))
            total_credit += amt
        if i % 3 == 0:  # partial repayments, including one fully cleared
            pay = total_credit if i % 6 == 0 else round(total_credit * 0.4)
            db.add(LedgerEntry(merchant_id=m.id, customer_id=c.id, kind="payment_received", amount=float(pay),
                               ts=now - timedelta(days=rng.randint(1, 10)), note="payment"))


REVIEWS_POS = ["Great service and fair prices", "Always fresh and the owner is very helpful", "Best shop in the area, quick billing",
               "Bahut accha saaman, price bhi sahi", "Quality ekdum badhiya hai", "Friendly staff, will come again"]
REVIEWS_NEU = ["Decent shop but gets crowded in the evening", "Okay quality, prices slightly high", "Theek hai, kabhi kabhi saaman nahi milta"]
REVIEWS_NEG = ["Had to wait very long at the counter", "Item was out of stock again, very disappointing",
               "Price was higher than MRP, not happy", "Staff was rude when I asked for a bill",
               "Bahut intezaar karna pada, service slow hai"]


def _seed_reviews(db, m, segment, rng, now):
    pool = [(5, REVIEWS_POS), (4, REVIEWS_POS), (3, REVIEWS_NEU), (2, REVIEWS_NEG), (1, REVIEWS_NEG)]
    for i in range(14):
        rating, texts = rng.choices(pool, weights=[38, 26, 14, 14, 8])[0]
        ts = now - timedelta(days=rng.randint(0, 40), hours=rng.randint(0, 20))
        replied = i % 3 == 0 and (now - ts).days > 6
        db.add(Review(merchant_id=m.id, source=rng.choice(["google", "paytm"]), author=f"{rng.choice(FIRST)} {rng.choice(LAST)[0]}.",
                      rating=rating, text=rng.choice(texts), ts=ts, replied=replied,
                      reply_text="Thank you for your feedback!" if replied else None))
    # A rating without any text: exercises that edge case.
    db.add(Review(merchant_id=m.id, source="google", author="Anonymous", rating=1, text="", ts=now - timedelta(days=1)))


# Demo deduction rates (real rates depend on the merchant's Paytm plan). UPI is 0% for small merchants.
COMMISSION_PCT = {"UPI": 0.0, "CARD": 1.8, "WALLET": 1.0}
GST_ON_COMMISSION = 0.18


def _seed_settlements(db, m, rng, today):
    """One settlement per day. Invariant: amount (net) = gross - sum(lines)."""
    for back in range(1, 15):
        d = today - timedelta(days=back)
        start = datetime(d.year, d.month, d.day)
        day = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.ts >= start,
                                           Transaction.ts < start + timedelta(days=1)).all()
        ok = [t for t in day if t.status == "success"]
        gross = round(sum(t.amount for t in ok), 2)
        exp = d + timedelta(days=1)
        # skip weekend settlement like banks do (settles Monday)
        while exp.weekday() >= 6:
            exp += timedelta(days=1)
        status, settled, reason = "settled", exp, None
        if back == 2:
            status, settled = "pending", None  # delayed settlement (past expected date)
        if back == 5 and m.segment == "kirana":
            status, settled, reason = "failed", None, "Beneficiary bank account inactive"
        lines: list[tuple[str, str, float]] = []
        comm = round(sum(t.amount * COMMISSION_PCT[t.mode] / 100 for t in ok), 2)
        if comm > 0:
            lines.append(("commission", "Commission (card & wallet payments)", comm))
            lines.append(("gst", "GST @18% on commission", round(comm * GST_ON_COMMISSION, 2)))
        refunds = round(sum(t.amount for t in day if t.status == "refunded"), 2)
        if refunds > 0:
            lines.append(("refund", "Refunds to customers", refunds))
        if m.soundbox_id and back == 7:
            lines.append(("rental", "Soundbox rental (monthly)", 125.0))
        if m.segment == "kirana" and back == 9:
            lines.append(("chargeback", "Chargeback debited: proof of delivery not sent in time", 850.0))
        net = round(gross - sum(a for _, _, a in lines), 2)
        s = Settlement(merchant_id=m.id, amount=max(net, 0.0), expected_date=exp, settled_date=settled,
                       status=status, utr=f"UTR{m.id}{d.strftime('%y%m%d')}{rng.randint(1000, 9999)}", failure_reason=reason)
        db.add(s)
        db.flush()
        for kind, label, amt in lines:
            db.add(SettlementLine(settlement_id=s.id, kind=kind, label=label, amount=amt))
    db.flush()


def _seed_chargebacks(db, m, today):
    """Ramesh Kirana (demo): one chargeback whose proof deadline is two days away, one already lost."""
    if m.segment != "kirana":
        return
    since = datetime(today.year, today.month, today.day) - timedelta(days=14)
    cands = db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.status == "success",
                                         Transaction.ts >= since, Transaction.amount >= 150).order_by(Transaction.amount.desc()).limit(3).all()
    if len(cands) < 2:
        return
    open_t, lost_t = cands[0], cands[1]
    db.add(Chargeback(merchant_id=m.id, txn_id=open_t.id, amount=round(open_t.amount, 2), raised_date=today - timedelta(days=5),
                      proof_due_date=today + timedelta(days=2), status="open",
                      reason="Customer's bank says the goods were not received"))
    db.add(Chargeback(merchant_id=m.id, txn_id=lost_t.id, amount=850.0, raised_date=today - timedelta(days=16),
                      proof_due_date=today - timedelta(days=9), status="lost", reason="Proof of delivery was not sent before the deadline"))
    db.flush()


def _seed_payables(db, m, sups, segment, today):
    if not sups:
        db.add(Payable(merchant_id=m.id, supplier_id=None, amount=18000.0, due_date=today + timedelta(days=12), note="Salon rent"))
        return
    if segment == "sweets":  # post-Diwali dip + big raw-material bills => cash gap
        db.add(Payable(merchant_id=m.id, supplier_id=sups[0].id, amount=185000.0, due_date=today + timedelta(days=4), note="Mawa & dry fruit bill"))
        db.add(Payable(merchant_id=m.id, supplier_id=sups[2].id, amount=96000.0, due_date=today + timedelta(days=8), note="Ghee bill"))
        db.add(Payable(merchant_id=m.id, supplier_id=None, amount=42000.0, due_date=today + timedelta(days=6), note="Staff salaries"))
    else:
        db.add(Payable(merchant_id=m.id, supplier_id=sups[0].id, amount=22000.0, due_date=today + timedelta(days=9), note="Monthly grocery bill"))
        db.add(Payable(merchant_id=m.id, supplier_id=sups[2].id, amount=9500.0, due_date=today + timedelta(days=15), note="FMCG bill"))


if __name__ == "__main__":
    from .db import SessionLocal

    with SessionLocal() as s:
        print("seeded merchants:", seed(s))


def sample_spec_for(segment: str) -> dict:
    """Catalogue/behaviour template for 'explore with sample data'. Unknown segments use the kirana template."""
    return next((s for s in MERCHANTS if s["segment"] == segment), MERCHANTS[0])


def clear_merchant_data(db: Session, m: Merchant) -> None:
    """Delete everything populate() created (children first). The merchant, consents and sessions are kept."""
    from .models import (Action, AuditLog, Briefing, ChatMessage, Outbox)
    txn_ids = [i for (i,) in db.query(Transaction.id).filter_by(merchant_id=m.id)]
    for k in range(0, len(txn_ids), 500):
        db.query(TxnItem).filter(TxnItem.txn_id.in_(txn_ids[k:k + 500])).delete(synchronize_session=False)
    sids = [i for (i,) in db.query(Settlement.id).filter_by(merchant_id=m.id)]
    for k in range(0, len(sids), 500):
        db.query(SettlementLine).filter(SettlementLine.settlement_id.in_(sids[k:k + 500])).delete(synchronize_session=False)
    db.query(Chargeback).filter_by(merchant_id=m.id).delete(synchronize_session=False)
    for model in (Transaction, LedgerEntry, Review, Settlement, Payable, Outbox, Action, Briefing, ChatMessage):
        db.query(model).filter_by(merchant_id=m.id).delete(synchronize_session=False)
    db.query(Item).filter_by(merchant_id=m.id).delete(synchronize_session=False)
    db.query(Customer).filter_by(merchant_id=m.id).delete(synchronize_session=False)
    db.query(Supplier).filter_by(merchant_id=m.id).delete(synchronize_session=False)
    m.sample_data = False
