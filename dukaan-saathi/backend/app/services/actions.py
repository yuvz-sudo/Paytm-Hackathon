"""Approval workflow. The agent can only *propose*; execution happens here after an explicit yes.

Guarantees: idempotent approve/reject, TTL expiry, de-duplication of identical proposals,
re-validation at execution time (e.g. don't remind a customer who has since paid), consent check
for outbound messaging, and an audit trail for every state change."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import clock, config
from ..models import Action, Chargeback, Customer, Merchant, Outbox
from . import audit, consent
from . import ledger as ledger_svc


def _dict(a: Action) -> dict:
    return {"id": a.id, "kind": a.kind, "title": a.title, "payload": a.payload, "status": a.status,
            "created_at": a.created_at.isoformat(), "expires_at": a.expires_at.isoformat(),
            "decided_at": a.decided_at.isoformat() if a.decided_at else None, "result": a.result}


def expire_stale(db: Session, merchant_id: int) -> None:
    db.query(Action).filter(Action.merchant_id == merchant_id, Action.status == "pending", Action.expires_at < clock.now()).update(
        {"status": "expired"}, synchronize_session=False)
    db.commit()


def propose(db: Session, m: Merchant, kind: str, title: str, payload: dict, dedupe_key: str | None = None, actor: str = "agent") -> dict:
    expire_stale(db, m.id)
    if dedupe_key:
        existing = db.query(Action).filter_by(merchant_id=m.id, dedupe_key=dedupe_key, status="pending").first()
        if existing:
            return {**_dict(existing), "deduplicated": True}
    now = clock.now()
    a = Action(merchant_id=m.id, kind=kind, title=title, payload=payload, dedupe_key=dedupe_key, created_at=now,
               expires_at=now + timedelta(hours=config.ACTION_TTL_HOURS))
    db.add(a)
    audit.log(db, m.id, actor, "action_proposed", {"kind": kind, "title": title})
    db.commit()
    return _dict(a)


def list_actions(db: Session, merchant_id: int, status: str | None = "pending") -> list[dict]:
    expire_stale(db, merchant_id)
    q = db.query(Action).filter_by(merchant_id=merchant_id)
    if status:
        q = q.filter_by(status=status)
    return [_dict(a) for a in q.order_by(Action.id.desc()).limit(100)]


def reject(db: Session, merchant_id: int, action_id: int) -> dict:
    expire_stale(db, merchant_id)
    res = db.execute(update(Action).where(Action.id == action_id, Action.merchant_id == merchant_id, Action.status == "pending")
                     .values(status="rejected", decided_at=clock.now()))
    if res.rowcount == 0:
        db.rollback()
        return _state_error(db, merchant_id, action_id)
    audit.log(db, merchant_id, "merchant", "action_rejected", {"action_id": action_id})
    db.commit()
    return {"ok": True, "status": "rejected", "action_id": action_id}


def _state_error(db: Session, merchant_id: int, action_id: int) -> dict:
    a = db.get(Action, action_id)
    if not a or a.merchant_id != merchant_id:
        return {"ok": False, "error": "not_found"}
    return {"ok": False, "error": f"already_{a.status}", "status": a.status, "conflict": True}


def approve(db: Session, merchant_id: int, action_id: int, edited_message: str | None = None) -> dict:
    """Atomically claim the action (pending -> executing) so double taps / retries cannot double-send."""
    expire_stale(db, merchant_id)
    res = db.execute(update(Action).where(Action.id == action_id, Action.merchant_id == merchant_id, Action.status == "pending")
                     .values(status="executing", decided_at=clock.now()))
    db.commit()
    if res.rowcount == 0:
        return _state_error(db, merchant_id, action_id)
    a = db.get(Action, action_id)
    if edited_message is not None:
        edited_message = edited_message.strip()
        if not edited_message or len(edited_message) > 1000:
            a.status = "pending"  # release the claim; invalid edit
            db.commit()
            return {"ok": False, "error": "invalid_edited_message"}
        payload = dict(a.payload)
        payload["message"] = edited_message
        payload["edited"] = True
        if a.kind == "winback_offer":  # edited text applies to every recipient; {name} is personalised
            payload["recipients"] = [{**r, "message": edited_message.replace("{name}", r["name"].split()[0])}
                                     for r in payload.get("recipients", [])]
        if a.kind == "campaign_send":  # edited text applies to every recipient; {name} is personalised
            payload["recipients"] = [{**r, "message": edited_message.replace("{name}", r["name"].split()[0])} for r in payload.get("recipients", [])]
        a.payload = payload
    audit.log(db, merchant_id, "merchant", "action_approved", {"action_id": a.id, "kind": a.kind, "edited": edited_message is not None})
    try:
        result = _execute(db, a)
        a.status = "executed" if result.get("ok") else "failed"
        a.result = result.get("summary") or result.get("error")
    except consent.ConsentDenied as e:
        a.status, a.result = "failed", f"consent_off:{e.scope}"
        result = {"ok": False, "error": f"consent_off:{e.scope}"}
    except Exception as e:  # never leave a claim hanging
        a.status, a.result = "failed", f"error:{type(e).__name__}"
        result = {"ok": False, "error": "execution_failed"}
    audit.log(db, merchant_id, "system", "action_" + a.status, {"action_id": a.id, "result": a.result})
    from . import briefing
    briefing.invalidate(db, merchant_id)
    db.commit()
    from . import delivery
    return {**result, "status": a.status, "action_id": a.id, "deliveries": delivery.for_action(db, merchant_id, a.id)}


def _send(db: Session, a: Action, to_name: str, to_phone: str, body: str, channel: str = "whatsapp") -> None:
    db.add(Outbox(merchant_id=a.merchant_id, action_id=a.id, channel=channel, to_name=to_name, to_phone=to_phone,
                  body=body, created_at=clock.now()))


def _execute(db: Session, a: Action) -> dict:
    p = a.payload
    if a.kind in ("supplier_order", "udhaar_reminder", "winback_offer", "campaign_send"):
        consent.require(db, a.merchant_id, "messaging")

    if a.kind == "supplier_order":
        if not p.get("phone"):
            return {"ok": False, "error": "supplier_has_no_phone"}
        _send(db, a, p["supplier_name"], p["phone"], p["message"])
        return {"ok": True, "summary": f"Order sent to {p['supplier_name']}"}

    if a.kind == "udhaar_reminder":
        c = db.get(Customer, p["customer_id"])
        if not c or c.merchant_id != a.merchant_id:
            return {"ok": False, "error": "customer_not_found"}
        if c.do_not_contact:
            return {"ok": False, "error": "customer_opted_out"}
        bal = ledger_svc.balance(db, a.merchant_id, c.id)
        if bal <= 0:
            return {"ok": False, "error": "already_paid", "summary": f"{c.name} has already cleared the dues"}
        msg = p["message"]
        if abs(bal - p["amount"]) > 0.5 and "message" in p and not p.get("edited"):
            # amount changed since the draft was written; resend with the live balance
            from .. import messages  # local import to avoid cycle
            m = db.get(Merchant, a.merchant_id)
            msg = messages.udhaar_reminder(m.language, m.name, c.name, bal, p.get("overdue_days", 0))
        _send(db, a, c.name, c.phone, msg)
        return {"ok": True, "summary": f"Reminder sent to {c.name}"}

    if a.kind == "winback_offer":
        sent = skipped = 0
        for r in p["recipients"]:
            c = db.get(Customer, r["id"])
            if not c or c.merchant_id != a.merchant_id or c.do_not_contact:
                skipped += 1
                continue
            _send(db, a, c.name, c.phone, r["message"])
            sent += 1
        if sent == 0:
            return {"ok": False, "error": "no_eligible_recipients"}
        return {"ok": True, "summary": f"Offer sent to {sent} customers" + (f" ({skipped} skipped)" if skipped else "")}

    if a.kind == "campaign_send":
        from . import marketing
        sent = skipped = 0
        for r in p["recipients"]:
            c = db.get(Customer, r["id"])
            if not c or c.merchant_id != a.merchant_id or c.do_not_contact:
                skipped += 1
                continue
            _send(db, a, c.name, c.phone, r["message"])
            sent += 1
        if sent == 0:
            return {"ok": False, "error": "no_eligible_recipients"}
        marketing.mark_sent(db, db.get(Merchant, a.merchant_id), p["campaign_id"])
        return {"ok": True, "summary": f"Campaign saved to your outbox for {sent} customers" + (f" ({skipped} skipped)" if skipped else "")}

    if a.kind == "chargeback_proof":
        # goes to Paytm's dispute team, not a customer, so it is not blocked by the marketing-messaging consent
        c = db.get(Chargeback, p["chargeback_id"])
        if not c or c.merchant_id != a.merchant_id:
            return {"ok": False, "error": "chargeback_not_found"}
        if c.status != "open":
            return {"ok": False, "error": "chargeback_not_open", "summary": f"This chargeback is already {c.status.replace('_', ' ')}"}
        if c.proof_due_date < clock.today():
            return {"ok": False, "error": "deadline_passed", "summary": "The deadline to send proof has passed"}
        _send(db, a, "Paytm Disputes", "", p["message"], channel="email")
        c.status = "proof_sent"
        return {"ok": True, "summary": "Proof sent to Paytm. Remember to attach your bill or delivery record."}

    return {"ok": False, "error": "unknown_action_kind"}
