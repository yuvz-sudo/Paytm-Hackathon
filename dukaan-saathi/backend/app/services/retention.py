"""Customer retention segments: who is new, repeat, high-value, drifting away or gone, each with their usual item.
Only customers who paid through Paytm with an identified customer id can be segmented. Pure functions; no LLM."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median

from sqlalchemy.orm import Session

from .. import clock
from ..models import Customer, Item, Merchant, Transaction, TxnItem
from ..util import inr

NEW_DAYS = 30
LAPSED_MAX_DAYS = 120
HIGH_VALUE_PCT = 0.8  # top 20% by spend among repeat customers
SEGMENTS = ("high_value", "repeat", "new", "at_risk", "lapsed")
LABELS = {"high_value": "High-value", "repeat": "Repeat", "new": "New", "at_risk": "Drifting away", "lapsed": "Lapsed"}
HELP = {"high_value": "Your biggest spenders who still visit", "repeat": "Come back regularly", "new": "First visit in the last 30 days",
        "at_risk": "Visiting less often than usual, not gone yet", "lapsed": "Regulars who stopped coming"}
# Default offer per segment (all clamped by the merchant's discount cap when the offer is created)
OFFER = {"high_value": {"pct": 0, "occasion": "Thank you"}, "repeat": {"pct": 5, "occasion": "Loyalty offer"},
         "new": {"pct": 5, "occasion": "Welcome back"}, "at_risk": {"pct": 7, "occasion": "We miss you"}, "lapsed": {"pct": 12, "occasion": "We miss you"}}


def _favourites(db: Session, mid: int, txn_ids: list[int]) -> dict[int, str]:
    """customer_id -> most bought item, from itemised payments only."""
    if not txn_ids:
        return {}
    cust_of = {}
    for k in range(0, len(txn_ids), 500):
        for tid, cid in db.query(Transaction.id, Transaction.customer_id).filter(Transaction.id.in_(txn_ids[k:k + 500])):
            cust_of[tid] = cid
    names = {i.id: i.name for i in db.query(Item).filter_by(merchant_id=mid)}
    cnt: dict[int, Counter] = defaultdict(Counter)
    tids = list(cust_of)
    for k in range(0, len(tids), 500):
        for ti in db.query(TxnItem).filter(TxnItem.txn_id.in_(tids[k:k + 500])):
            cnt[cust_of[ti.txn_id]][ti.item_id] += 1
    return {cid: names[c.most_common(1)[0][0]] for cid, c in cnt.items() if c and c.most_common(1)[0][0] in names}


def _compute(db: Session, m: Merchant) -> list[dict]:
    """Every identified customer with a segment (or None), spend, visits and usual item."""
    today = clock.today()
    since = clock.now() - timedelta(days=180)
    visits: dict[int, list] = defaultdict(list)
    for t in db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.customer_id.isnot(None), Transaction.status == "success",
                                          Transaction.ts >= since):
        visits[t.customer_id].append(t)
    custs = {c.id: c for c in db.query(Customer).filter_by(merchant_id=m.id)}
    rows = []
    for cid, txns in visits.items():
        c = custs.get(cid)
        if not c:
            continue
        days = sorted({t.ts.date() for t in txns})
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        rows.append({"customer_id": cid, "name": c.name, "phone": c.phone, "do_not_contact": c.do_not_contact, "visits": len(days),
                     "spend": round(sum(t.amount for t in txns), 2), "first": days[0], "days_since": (today - days[-1]).days,
                     "typical_gap_days": median(gaps) if gaps else None, "txn_ids": [t.id for t in txns]})
    spends = sorted(r["spend"] for r in rows if r["visits"] >= 3)
    hv_cut = spends[int(len(spends) * HIGH_VALUE_PCT)] if len(spends) >= 5 else None
    for r in rows:
        v, ds, ty = r["visits"], r["days_since"], r["typical_gap_days"]
        if v >= 3 and ty is not None and ds > max(14, 2.5 * ty) and ds <= LAPSED_MAX_DAYS:
            seg = "lapsed"
        elif v >= 3 and ty is not None and ds > max(10, 1.5 * ty) and ds <= LAPSED_MAX_DAYS:
            seg = "at_risk"
        elif hv_cut is not None and v >= 3 and r["spend"] >= hv_cut:
            seg = "high_value"
        elif (today - r["first"]).days <= NEW_DAYS and v <= 2:
            seg = "new"
        elif v >= 2 and ds <= 90:
            seg = "repeat"
        else:
            seg = None  # one-off or long gone: not worth a campaign
        r["segment"] = seg
    fav = _favourites(db, m.id, [tid for r in rows if r["segment"] for tid in r["txn_ids"]])
    for r in rows:
        r["usual_item"] = fav.get(r["customer_id"])
    return rows


def segments(db: Session, m: Merchant) -> dict:
    rows = _compute(db, m)
    if not rows:
        return {"no_data": True, "segments": [], "identified": 0}
    out = []
    for s in SEGMENTS:
        members = sorted((r for r in rows if r["segment"] == s), key=lambda r: -r["spend"])
        out.append({"id": s, "label": LABELS[s], "help": HELP[s], "count": len(members), "spend": round(sum(r["spend"] for r in members), 2),
                    "reachable": sum(1 for r in members if r["phone"] and not r["do_not_contact"]), "default_offer": OFFER[s],
                    "members": [{"customer_id": r["customer_id"], "name": r["name"], "visits": r["visits"], "spend": r["spend"],
                                 "days_since": r["days_since"], "usual_item": r["usual_item"]} for r in members[:8]]})
    return {"no_data": False, "identified": len(rows), "segments": out, "unsegmented": sum(1 for r in rows if r["segment"] is None),
            "summary": f"{len(rows)} known customers: " + ", ".join(f"{x['count']} {x['label'].lower()}" for x in out if x["count"]) + "."}


def audience(db: Session, m: Merchant, segment: str, limit: int = 100) -> list[dict]:
    """Contactable members of one segment, best spenders first, with their usual item (for personalised campaigns)."""
    rows = [r for r in _compute(db, m) if r["segment"] == segment and r["phone"] and not r["do_not_contact"]]
    rows.sort(key=lambda r: -r["spend"])
    return [{"id": r["customer_id"], "name": r["name"], "phone": r["phone"], "item": r["usual_item"]} for r in rows[:limit]]


def counts(db: Session, m: Merchant) -> dict[str, int]:
    """Reachable customers per segment (what a campaign to that segment would actually send to)."""
    out = {s: 0 for s in SEGMENTS}
    for r in _compute(db, m):
        if r["segment"] and r["phone"] and not r["do_not_contact"]:
            out[r["segment"]] += 1
    return out
