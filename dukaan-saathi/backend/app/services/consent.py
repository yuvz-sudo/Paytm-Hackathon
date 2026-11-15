"""Consent is the first gate for every read of merchant data and every proactive message."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import clock
from ..models import Consent
from . import audit

SCOPES = {
    "transactions": "Payments, settlements and sales insights",
    "customers": "Customer visit history (for win-back offers)",
    "ledger": "Udhaar / credit book",
    "credit": "Cash-flow analysis for credit suggestions",
    "messaging": "Sending messages on my behalf (always after my approval)",
}


class ConsentDenied(Exception):
    def __init__(self, scope: str):
        self.scope = scope
        super().__init__(f"consent_off:{scope}")


def is_granted(db: Session, merchant_id: int, scope: str) -> bool:
    row = db.get(Consent, (merchant_id, scope))
    return bool(row and row.granted)


def require(db: Session, merchant_id: int, scope: str) -> None:
    if not is_granted(db, merchant_id, scope):
        raise ConsentDenied(scope)


def all_for(db: Session, merchant_id: int) -> list[dict]:
    rows = {c.scope: c for c in db.query(Consent).filter_by(merchant_id=merchant_id)}
    return [{"scope": s, "label": label, "granted": bool(rows.get(s) and rows[s].granted)} for s, label in SCOPES.items()]


def set_scope(db: Session, merchant_id: int, scope: str, granted: bool) -> None:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope}")
    row = db.get(Consent, (merchant_id, scope))
    if row is None:
        row = Consent(merchant_id=merchant_id, scope=scope, granted=granted, updated_at=clock.now())
        db.add(row)
    else:
        row.granted, row.updated_at = granted, clock.now()
    audit.log(db, merchant_id, "merchant", "consent_changed", {"scope": scope, "granted": granted})
    from . import briefing
    briefing.invalidate(db, merchant_id)
    db.commit()
