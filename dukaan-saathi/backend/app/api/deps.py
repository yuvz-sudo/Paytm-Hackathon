"""Request authentication. Bearer session first; the X-Merchant-Id demo header only when ALLOW_DEMO_HEADER is on."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import config, demo_clock
from ..db import get_db
from ..models import Merchant
from ..services import auth, consent


def bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def session_merchant(authorization: str | None = Header(default=None), x_merchant_id: int | None = Header(default=None),
                     db: Session = Depends(get_db)) -> Merchant:
    """Identifies the caller. Does NOT require onboarding to be finished (used by sign-up endpoints)."""
    token = bearer_token(authorization)
    if token:
        m = auth.merchant_for_token(db, token)
        if not m:
            raise HTTPException(401, {"error": "invalid_session"})
        demo_clock.refresh(db, m)
        return m
    if config.ALLOW_DEMO_HEADER and x_merchant_id is not None:
        m = db.get(Merchant, x_merchant_id)
        if not m:
            raise HTTPException(404, "merchant_not_found")
        demo_clock.refresh(db, m)
        return m
    raise HTTPException(401, {"error": "login_required"})


def current_merchant(m: Merchant = Depends(session_merchant)) -> Merchant:
    if not m.onboarded:
        raise HTTPException(403, {"error": "onboarding_required"})
    if not m.opted_in:
        raise HTTPException(403, {"error": "not_opted_in"})
    return m


def need(scope: str):
    def dep(m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)) -> Merchant:
        if not consent.is_granted(db, m.id, scope):
            raise HTTPException(403, {"error": "consent_off", "scope": scope})
        return m
    return dep
