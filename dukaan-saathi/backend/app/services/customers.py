"""Repeat-customer intelligence: who are the regulars and who stopped coming."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import median

from sqlalchemy.orm import Session

from .. import clock, config, messages
from ..models import Customer, Merchant, Transaction
from ..util import hour_label, inr
from . import actions, analytics, consent

MIN_VISITS = 3
MAX_LAPSED_DAYS = 120  # beyond this they are churned, not "lapsed"


def _visits(db: Session, m: Merchant) -> dict[int, list]:
    since = clock.now() - timedelta(days=180)
    by: dict[int, list] = defaultdict(list)
    for t in db.query(Transaction).filter(Transaction.merchant_id == m.id, Transaction.customer_id.isnot(None),
                                          Transaction.status == "success", Transaction.ts >= since):
        by[t.customer_id].append(t)
    return by


def summary(db: Session, m: Merchant) -> dict:
    today = clock.today()
    visits = _visits(db, m)
    custs = {c.id: c for c in db.query(Customer).filter_by(merchant_id=m.id)}
    regulars, lapsed = [], []
    for cid, txns in visits.items():
        c = custs.get(cid)
        if not c:
            continue
        days = sorted({t.ts.date() for t in txns})
        spend = round(sum(t.amount for t in txns), 2)
        last = days[-1]
        since = (today - last).days
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        typical = median(gaps) if gaps else None
        row = {"customer_id": cid, "name": c.name, "phone": c.phone, "visits": len(days), "total_spend": spend,
               "last_visit": last.isoformat(), "days_since": since, "typical_gap_days": typical,
               "do_not_contact": c.do_not_contact}
        if len(days) >= MIN_VISITS and typical is not None and since > max(14, 2.5 * typical) and since <= MAX_LAPSED_DAYS:
            lapsed.append(row)
        if len(days) >= MIN_VISITS:
            regulars.append(row)
    lapsed.sort(key=lambda r: r["total_spend"], reverse=True)
    regulars.sort(key=lambda r: r["total_spend"], reverse=True)
    month_start = clock.now() - timedelta(days=30)
    recent_ids = {cid for cid, txns in visits.items() if any(t.ts >= month_start for t in txns)}
    repeat = [cid for cid in recent_ids if len({t.ts.date() for t in visits[cid] if t.ts >= month_start}) >= 2]
    return {"lapsed": lapsed, "top_regulars": regulars[:5], "all_regulars": regulars[:100], "suggested_window": quiet_window(db, m), "identified_customers": len(visits),
            "active_30d": len(recent_ids), "repeat_30d": len(repeat),
            "at_risk_revenue": round(sum(r["total_spend"] for r in lapsed), 2)}


def quiet_window(db: Session, m: Merchant, send_hour: int | None = None) -> dict | None:
    """The hour(s) to steer an offer into. Defaults to the next upcoming quiet hour from the shop's own hourly sales
    (slow hours, else the two quietest). Returns None when we have no sales data or the merchant switched that access off.
    An explicit `send_hour` (0-23) is honoured as given; it must be validated by the caller."""
    if not consent.is_granted(db, m.id, "transactions"):
        return None
    prof = analytics.hourly_profile(db, m)
    if prof.get("no_data"):
        return None
    pool = set(prof["slow_hours"] or prof["quietest_hours"])
    now = clock.now()
    if send_hour is None:
        # next quiet hour from now (today if still ahead, otherwise tomorrow)
        start = min(pool, key=lambda h: ((h - now.hour - 1) % 24, h))
        source = "slow_hours" if prof["slow_hours"] else "quietest_hours"
    else:
        start, source = send_hour, "chosen_by_merchant"
        pool = pool | {send_hour}
    end = start + 1
    while end % 24 in pool and end - start < 3 and end < 24:  # stretch over adjacent quiet hours, max 3 hours
        end += 1
    when = "today" if start > now.hour else "tomorrow"
    return {"start_hour": start, "end_hour": end, "label": f"{hour_label(start)} to {hour_label(end)}", "when": when, "source": source}


def propose_winback(db: Session, m: Merchant, discount_pct: int = 10, valid_days: int = 7, limit: int = 10,
                    send_hour: int | None = None) -> dict:
    cap = min(m.max_offer_discount_pct, config.MAX_OFFER_DISCOUNT_PCT)
    try:
        discount_pct = int(discount_pct)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_discount"}
    if discount_pct < 1:
        return {"ok": False, "error": "invalid_discount"}
    if send_hour is not None:
        try:
            send_hour = int(send_hour)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_hour"}
        if not 0 <= send_hour <= 23:
            return {"ok": False, "error": "invalid_hour"}
    clamped = discount_pct > cap
    discount_pct = min(discount_pct, cap)
    valid_days = max(1, min(int(valid_days), 30))
    s = summary(db, m)
    targets = [r for r in s["lapsed"] if not r["do_not_contact"] and r["phone"]][:limit]
    if not targets:
        return {"ok": False, "error": "no_lapsed_customers"}
    window = quiet_window(db, m, send_hour)
    wlabel = window["label"] if window else None
    recipients = [{"id": r["customer_id"], "name": r["name"], "phone": r["phone"],
                   "message": messages.winback_offer(m.language, m.name, r["name"], discount_pct, valid_days, wlabel)} for r in targets]
    a = actions.propose(
        db, m, "winback_offer", f"Send {discount_pct}% win-back offer to {len(recipients)} regulars",
        {"discount_pct": discount_pct, "valid_days": valid_days, "recipients": recipients, "window": window,
         "message": recipients[0]["message"], "at_risk_revenue": sum(r["total_spend"] for r in targets)},
        dedupe_key=f"winback:{discount_pct}:{len(recipients)}:{window['start_hour'] if window else 'any'}")
    return {"ok": True, "action": a, "recipients": len(recipients), "discount_pct": discount_pct, "discount_capped": clamped,
            "cap_pct": cap, "window": window}
