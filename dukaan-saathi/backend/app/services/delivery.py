"""Getting approved messages to people, honestly.

There is no WhatsApp Business API connected, so an approved message is not sent by a server. Instead each one gets a
one-tap WhatsApp link (wa.me) and an SMS link that open the merchant's own app with the recipient and the text filled in;
the merchant presses send. We track which ones were opened ("sent") so nothing is forgotten or sent twice."""
from __future__ import annotations

import re
from urllib.parse import quote

from sqlalchemy.orm import Session

from .. import clock
from ..models import DeliveryStatus, Outbox


def wa_number(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10 and digits[0] in "6789":
        return "91" + digits
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return digits
    return None


def view(row: Outbox, status: str | None) -> dict:
    num = wa_number(row.to_phone)
    st = status or ("ready" if row.channel in ("whatsapp", "sms") else "sent")
    return {"id": row.id, "to": row.to_name, "phone": row.to_phone, "channel": row.channel, "body": row.body,
            "ts": row.created_at.isoformat(), "action_id": row.action_id, "status": st,
            "whatsapp_url": f"https://wa.me/{num}?text={quote(row.body)}" if num else None,
            "sms_url": f"sms:+{num}?&body={quote(row.body)}" if num else None,
            "needs_number": row.channel in ("whatsapp", "sms") and not num}


def _statuses(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {d.outbox_id: d.status for d in db.query(DeliveryStatus).filter(DeliveryStatus.outbox_id.in_(ids))}


def listing(db: Session, merchant_id: int, limit: int = 60) -> list[dict]:
    rows = db.query(Outbox).filter_by(merchant_id=merchant_id).order_by(Outbox.id.desc()).limit(limit).all()
    st = _statuses(db, [r.id for r in rows])
    return [view(r, st.get(r.id)) for r in rows]


def for_action(db: Session, merchant_id: int, action_id: int) -> list[dict]:
    rows = db.query(Outbox).filter_by(merchant_id=merchant_id, action_id=action_id).order_by(Outbox.id).all()
    st = _statuses(db, [r.id for r in rows])
    return [view(r, st.get(r.id)) for r in rows]


def mark(db: Session, merchant_id: int, outbox_id: int, status: str) -> dict:
    row = db.query(Outbox).filter_by(id=outbox_id, merchant_id=merchant_id).first()
    if not row:
        return {"ok": False, "error": "not_found"}
    d = db.get(DeliveryStatus, outbox_id)
    if d:
        d.status, d.updated_at = status, clock.now()
    else:
        db.add(DeliveryStatus(outbox_id=outbox_id, merchant_id=merchant_id, status=status, updated_at=clock.now()))
    db.commit()
    return {"ok": True, **view(row, status)}
