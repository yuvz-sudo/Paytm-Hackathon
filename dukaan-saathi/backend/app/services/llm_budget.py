"""Daily LLM request budget per merchant. When it is spent, the app answers with its rule engine instead."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import clock, config
from ..models import LlmUsage


def _row(db: Session, mid: int, kind: str) -> LlmUsage:
    r = db.query(LlmUsage).filter_by(merchant_id=mid, day=clock.today(), kind=kind).first()
    if not r:
        r = LlmUsage(merchant_id=mid, day=clock.today(), kind=kind, requests=0, tokens=0)
        db.add(r)
        db.flush()
    return r


def poster_count(db: Session, mid: int) -> int:
    r = db.query(LlmUsage).filter_by(merchant_id=mid, day=clock.today(), kind="poster").first()
    return r.requests if r else 0


def used(db: Session, mid: int) -> int:
    return sum(r.requests for r in db.query(LlmUsage).filter_by(merchant_id=mid, day=clock.today()) if r.kind != "poster")


def allowed(db: Session, mid: int, need: int = 1) -> bool:
    return used(db, mid) + need <= config.LLM_DAILY_REQUESTS


def record(db: Session, mid: int, kind: str = "chat", requests: int = 1, tokens: int = 0) -> None:
    r = _row(db, mid, kind)
    r.requests += requests
    r.tokens += tokens
    db.commit()


def summary(db: Session, mid: int) -> dict:
    rows = db.query(LlmUsage).filter_by(merchant_id=mid, day=clock.today()).all()
    n = sum(r.requests for r in rows if r.kind != "poster")
    return {"day": clock.today().isoformat(), "requests": n, "tokens": sum(r.tokens for r in rows), "limit": config.LLM_DAILY_REQUESTS,
            "remaining": max(config.LLM_DAILY_REQUESTS - n, 0), "mode": config.LLM_MODE,
            "by_kind": {r.kind: {"requests": r.requests, "tokens": r.tokens} for r in rows}}
