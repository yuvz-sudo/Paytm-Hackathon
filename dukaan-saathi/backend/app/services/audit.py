from __future__ import annotations

from sqlalchemy.orm import Session

from .. import clock
from ..models import AuditLog


def log(db: Session, merchant_id: int, actor: str, event: str, detail: dict | None = None) -> None:
    db.add(AuditLog(merchant_id=merchant_id, ts=clock.now(), actor=actor, event=event, detail=detail or {}))


def recent(db: Session, merchant_id: int, limit: int = 50) -> list[dict]:
    rows = db.query(AuditLog).filter_by(merchant_id=merchant_id).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "ts": r.ts.isoformat(), "actor": r.actor, "event": r.event, "detail": r.detail} for r in rows]
