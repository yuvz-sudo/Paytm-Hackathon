"""Phone + OTP login and bearer sessions.

Security notes: OTPs are random 6 digits, stored salted+hashed, expire, are single use, are attempt-limited and
request-rate-limited per phone. Session tokens are 256-bit random; only their hash is stored. Responses never reveal
whether a phone number is already registered beyond what login itself implies."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import clock, config
from ..models import AuthSession, Merchant, OtpChallenge
from . import audit, sms

_PHONE = re.compile(r"^[6-9]\d{9}$")


class AuthError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def normalize_phone(raw: str) -> str:
    """Accepts '98765 43210', '+91-9876543210', '09876543210', '919876543210'. Returns +91XXXXXXXXXX."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _PHONE.match(digits):
        raise AuthError("invalid_phone", 422)
    return "+91" + digits


def _hash(code: str, salt: str) -> str:
    return hashlib.sha256((salt + code).encode()).hexdigest()


def request_otp(db: Session, raw_phone: str) -> dict:
    phone = normalize_phone(raw_phone)
    now = clock.now()
    recent = db.query(OtpChallenge).filter(OtpChallenge.phone == phone, OtpChallenge.created_at >= now - timedelta(hours=1)).count()
    if recent >= config.OTP_MAX_REQUESTS_PER_HOUR:
        raise AuthError("too_many_requests", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(8)
    # invalidate earlier unused codes so only the latest works
    db.query(OtpChallenge).filter(OtpChallenge.phone == phone, OtpChallenge.consumed.is_(False)).update({"consumed": True})
    db.add(OtpChallenge(phone=phone, code_hash=_hash(code, salt), salt=salt, created_at=now,
                        expires_at=now + timedelta(minutes=config.OTP_TTL_MINUTES)))
    try:
        if sms.uses_remote_check():
            sms.start_verification(phone)  # Twilio generates the code; ours is a placeholder for limits/expiry only
        else:
            sms.send_otp(phone, code)
    except sms.SmsError:
        db.rollback()  # a failed send must not burn the rate limit or invalidate the previous code
        raise AuthError("sms_failed", 502)
    db.commit()
    out = {"ok": True, "phone": phone, "expires_in_seconds": config.OTP_TTL_MINUTES * 60}
    if config.DEV_OTP_ECHO and not sms.uses_remote_check():
        out["dev_otp"] = code  # prototype only; see config
    return out


def verify_otp(db: Session, raw_phone: str, code: str) -> dict:
    phone = normalize_phone(raw_phone)
    code = (code or "").strip()
    now = clock.now()
    ch = (db.query(OtpChallenge).filter(OtpChallenge.phone == phone, OtpChallenge.consumed.is_(False))
          .order_by(OtpChallenge.id.desc()).first())
    if not ch or ch.expires_at < now:
        raise AuthError("otp_expired", 400)
    if ch.attempts >= config.OTP_MAX_ATTEMPTS:
        ch.consumed = True
        db.commit()
        raise AuthError("too_many_attempts", 429)
    ch.attempts += 1
    if sms.uses_remote_check():
        try:
            ok = code.isdigit() and 4 <= len(code) <= 10 and sms.check_verification(phone, code)
        except sms.SmsError:
            db.commit()
            raise AuthError("sms_failed", 502)
    else:
        ok = code.isdigit() and len(code) == 6 and hmac.compare_digest(_hash(code, ch.salt), ch.code_hash)
    if not ok:
        db.commit()
        raise AuthError("otp_incorrect", 400)
    ch.consumed = True

    m = db.query(Merchant).filter_by(phone=phone).first()
    new_user = m is None
    if new_user:
        m = Merchant(name="", owner_name="", segment="kirana", city="", language="hinglish", phone=phone,
                     opted_in=False, onboarded=False, sample_data=False)
        db.add(m)
        db.flush()
        audit.log(db, m.id, "merchant", "signed_up", {"phone_last4": phone[-4:]})
    audit.log(db, m.id, "merchant", "logged_in", {})
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), merchant_id=m.id, created_at=now,
                       expires_at=now + timedelta(days=config.SESSION_DAYS)))
    db.commit()
    return {"token": token, "new_user": new_user, "onboarded": m.onboarded, "merchant_id": m.id}


def merchant_for_token(db: Session, token: str) -> Merchant | None:
    if not token:
        return None
    row = db.query(AuthSession).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not row or row.expires_at < clock.now():
        return None
    return db.get(Merchant, row.merchant_id)


def logout(db: Session, token: str) -> None:
    db.query(AuthSession).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).delete()
    db.commit()
