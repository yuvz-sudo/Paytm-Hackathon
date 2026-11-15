from __future__ import annotations

from sqlalchemy.orm import Session

from .. import clock, i18n
from ..models import Chargeback, Merchant, Settlement, SettlementLine, Transaction
from ..util import inr
from . import actions

URGENT_DAYS = 3  # a chargeback with this many days (or fewer) left is flagged urgent


def status(db: Session, m: Merchant) -> dict:
    today = clock.today()
    rows = db.query(Settlement).filter_by(merchant_id=m.id).order_by(Settlement.expected_date.desc()).limit(30).all()
    delayed, failed, upcoming, recent = [], [], [], []
    for s in rows:
        item = {"id": s.id, "amount": s.amount, "expected_date": s.expected_date.isoformat(), "status": s.status,
                "utr": s.utr, "settled_date": s.settled_date.isoformat() if s.settled_date else None,
                "failure_reason": s.failure_reason}
        if s.status == "failed":
            failed.append(item)
        elif s.status == "pending" and s.expected_date < today:
            item["days_late"] = (today - s.expected_date).days
            delayed.append(item)
        elif s.status == "pending":
            upcoming.append(item)
        else:
            recent.append(item)
    return {"delayed": delayed, "failed": failed, "upcoming": upcoming, "recent": recent[:7],
            "stuck_amount": round(sum(x["amount"] for x in delayed + failed), 2),
            "pending_amount": round(sum(x["amount"] for x in upcoming), 2), "no_data": not rows}


# ------------------------------------------------------------------ settlement explainer
KIND_LABEL = {
    "commission": {"en": "commission", "hi": "कमीशन", "hinglish": "commission"},
    "gst": {"en": "18% GST on commission", "hi": "कमीशन पर 18% GST", "hinglish": "commission par 18% GST"},
    "rental": {"en": "device rental", "hi": "डिवाइस किराया", "hinglish": "device rental"},
    "refund": {"en": "refunds", "hi": "रिफंड", "hinglish": "refunds"},
    "chargeback": {"en": "a chargeback", "hi": "चार्जबैक", "hinglish": "chargeback"},
    "recovery": {"en": "recoveries", "hi": "रिकवरी", "hinglish": "recovery"},
}


def explain(db: Session, m: Merchant, settlement_id: int | None = None, amount: float | None = None) -> dict:
    """Why is the payout lower than sales? net = gross - commission - GST on commission - rental - refunds - chargebacks - recoveries.
    Without an id: the settlement matching `amount` if given, else the latest one that has money in it (settled, then pending)."""
    q = db.query(Settlement).filter_by(merchant_id=m.id)
    if settlement_id is not None:
        s = q.filter_by(id=settlement_id).first()
    elif amount is not None:
        s = q.filter(Settlement.amount.between(amount - 1, amount + 1)).order_by(Settlement.expected_date.desc()).first()
    else:
        s = q.filter(Settlement.status.in_(["settled", "pending"])).order_by(Settlement.expected_date.desc(), Settlement.id.desc()).first()
    if not s:
        return {"ok": False, "error": "not_found" if (settlement_id is not None or amount is not None) else "no_settlements"}
    lines = db.query(SettlementLine).filter_by(settlement_id=s.id).order_by(SettlementLine.id).all()
    deductions = [{"kind": l.kind, "label": l.label, "amount": round(l.amount, 2)} for l in lines]
    total_ded = round(sum(d["amount"] for d in deductions), 2)
    gross = round(s.amount + total_ded, 2)
    # sales are what the merchant sees in the app; the settlement for day D is paid on D+1 (or Monday after a weekend)
    open_cb = [c for c in chargebacks(db, m)["chargebacks"] if c["status"] == "open"]
    res = {"ok": True, "settlement": {"id": s.id, "expected_date": s.expected_date.isoformat(), "status": s.status, "utr": s.utr,
                                       "failure_reason": s.failure_reason,
                                       "settled_date": s.settled_date.isoformat() if s.settled_date else None},
           "gross": gross, "deductions": deductions, "total_deductions": total_ded, "net": round(s.amount, 2),
           "deduction_pct": round(total_ded / gross * 100, 1) if gross else 0.0,
           "has_breakdown": bool(deductions), "open_chargebacks": open_cb[:3],
           "note": "Rates in this demo are illustrative; your actual charges depend on your Paytm plan."}
    res["summary"] = summarize(res, m.language)
    return res


def summarize(r: dict, lang: str) -> str:
    """Plain-words explanation in en / hi / hinglish. Numbers come from the data, never invented."""
    lg = i18n.lang_of(lang)
    s = r["settlement"]
    net, gross = inr(r["net"], 2), inr(r["gross"], 2)
    if s["status"] == "failed":
        head = {"en": f"This {net} settlement failed: {s['failure_reason']}.", "hi": f"यह {net} का सेटलमेंट विफल रहा: {s['failure_reason']}।",
                "hinglish": f"Yeh {net} ka settlement fail hua: {s['failure_reason']}."}[lg]
        return head
    if not r["deductions"]:
        return {"en": f"Your payout is {net}. No deductions are recorded on it, so it equals your payments of {gross}.",
                "hi": f"आपका पेआउट {net} है। इस पर कोई कटौती दर्ज नहीं है, यह आपके भुगतान {gross} के बराबर है।",
                "hinglish": f"Aapka payout {net} hai. Isme koi katauti darj nahi hai, yeh aapke payments {gross} ke barabar hai."}[lg]
    parts = ", ".join(f"{inr(d['amount'], 2)} {KIND_LABEL.get(d['kind'], {}).get(lg, d['label'])}" for d in r["deductions"])
    text = {"en": f"Payments received were {gross}. Paytm deducted {parts}, a total of {inr(r['total_deductions'], 2)} ({r['deduction_pct']}%), so you get {net}.",
            "hi": f"मिले भुगतान {gross} थे। Paytm ने {parts} काटे, कुल {inr(r['total_deductions'], 2)} ({r['deduction_pct']}%), इसलिए आपको {net} मिलेंगे।",
            "hinglish": f"Aaye payments {gross} the. Paytm ne {parts} kaate, kul {inr(r['total_deductions'], 2)} ({r['deduction_pct']}%), isliye aapko {net} milenge."}[lg]
    if r["open_chargebacks"]:
        c = r["open_chargebacks"][0]
        text += {"en": f" Heads up: a {inr(c['amount'])} chargeback is open. Send proof within {max(c['days_left'], 0)} day(s) or it will be debited.",
                 "hi": f" ध्यान दें: {inr(c['amount'])} का चार्जबैक खुला है। {max(c['days_left'], 0)} दिन में सबूत भेजें, वरना यह कट जाएगा।",
                 "hinglish": f" Dhyan dein: {inr(c['amount'])} ka chargeback open hai. {max(c['days_left'], 0)} din mein proof bhejiye, warna kat jayega."}[lg]
    return text


# ------------------------------------------------------------------ chargebacks
def chargebacks(db: Session, m: Merchant) -> dict:
    today = clock.today()
    rows = db.query(Chargeback).filter_by(merchant_id=m.id).order_by(Chargeback.proof_due_date).all()
    out = []
    for c in rows:
        days_left = (c.proof_due_date - today).days
        is_open = c.status == "open"
        out.append({"id": c.id, "txn_id": c.txn_id, "amount": round(c.amount, 2), "raised_date": c.raised_date.isoformat(),
                    "proof_due_date": c.proof_due_date.isoformat(), "status": c.status, "reason": c.reason,
                    "days_left": days_left, "overdue": is_open and days_left < 0,
                    "urgent": is_open and days_left <= URGENT_DAYS})
    open_ = [c for c in out if c["status"] == "open"]
    return {"chargebacks": out, "open_count": len(open_), "open_amount": round(sum(c["amount"] for c in open_), 2),
            "urgent_count": sum(1 for c in open_ if c["urgent"]), "no_data": not out}


def propose_proof(db: Session, m: Merchant, chargeback_id: int | None = None) -> dict:
    """Draft the proof-of-delivery message to Paytm's dispute team. Nothing is sent until the merchant approves."""
    q = db.query(Chargeback).filter_by(merchant_id=m.id, status="open")
    c = q.filter_by(id=chargeback_id).first() if chargeback_id is not None else q.order_by(Chargeback.proof_due_date).first()
    if not c:
        exists = chargeback_id is not None and db.query(Chargeback).filter_by(merchant_id=m.id, id=chargeback_id).first()
        return {"ok": False, "error": "chargeback_not_open" if exists else "not_found" if chargeback_id is not None else "no_open_chargeback"}
    today = clock.today()
    if c.proof_due_date < today:
        return {"ok": False, "error": "deadline_passed", "proof_due_date": c.proof_due_date.isoformat()}
    t = db.get(Transaction, c.txn_id) if c.txn_id else None
    when = t.ts.strftime("%d %b %Y, %I:%M %p") if t else c.raised_date.isoformat()
    msg = (f"Subject: Proof of delivery for chargeback #{c.id}\n\n"
           f"Hello Paytm Disputes team,\n\n{m.name} ({m.city}) is responding to chargeback #{c.id} of {inr(c.amount)}"
           + (f" against payment #{t.id} received on {when}" if t else "") + f". Reason given: {c.reason or 'not stated'}.\n\n"
           "We delivered the goods/services for this payment. Our proof (bill, delivery or service record) is attached. "
           "Please review and reverse the chargeback.\n\nRegards,\n" + m.owner_name)
    a = actions.propose(db, m, "chargeback_proof", f"Send proof for {inr(c.amount)} chargeback (due {c.proof_due_date.strftime('%d %b')})",
                        {"chargeback_id": c.id, "amount": c.amount, "message": msg, "proof_due_date": c.proof_due_date.isoformat(),
                         "needs_attachment": True}, dedupe_key=f"chargeback_proof:{c.id}")
    return {"ok": True, "action": a, "chargeback_id": c.id, "days_left": (c.proof_due_date - today).days,
            "reminder": "Attach your bill or delivery proof before approving."}
