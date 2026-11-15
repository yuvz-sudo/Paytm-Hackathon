"""SMS delivery for OTPs. Pick a provider with SMS_PROVIDER=console|twilio|msg91 (default console: logs only, sends nothing)."""
from __future__ import annotations

import logging

import httpx

from .. import config

log = logging.getLogger("dukaan.sms")


class SmsError(Exception):
    pass


def _twilio(phone: str, code: str) -> None:
    sid, token = config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN
    if not (sid and token and (config.TWILIO_FROM or config.TWILIO_MESSAGING_SERVICE_SID)):
        raise SmsError("twilio_not_configured")
    data = {"To": phone, "Body": f"Your Dukaan Saathi OTP is {code}. Valid for {config.OTP_TTL_MINUTES} minutes. Do not share it."}
    if config.TWILIO_MESSAGING_SERVICE_SID:
        data["MessagingServiceSid"] = config.TWILIO_MESSAGING_SERVICE_SID
    else:
        data["From"] = config.TWILIO_FROM
    r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data, auth=(sid, token), timeout=10)
    if r.status_code >= 300:
        log.error("Twilio rejected SMS: %s", r.text[:300])
        raise SmsError(f"twilio_{r.status_code}")


def _msg91(phone: str, code: str) -> None:
    if not (config.MSG91_AUTH_KEY and config.MSG91_TEMPLATE_ID):
        raise SmsError("msg91_not_configured")
    r = httpx.post("https://control.msg91.com/api/v5/otp",
                   params={"template_id": config.MSG91_TEMPLATE_ID, "mobile": phone.lstrip("+"), "authkey": config.MSG91_AUTH_KEY,
                           "otp": code, "otp_expiry": config.OTP_TTL_MINUTES},
                   timeout=10)
    if r.status_code >= 300 or r.json().get("type") == "error":
        raise SmsError(f"msg91_{r.status_code}")


def _console(phone: str, code: str) -> None:
    log.warning("OTP for %s (console provider, nothing sent): %s", phone, code)


def _verify_base() -> tuple[str, tuple[str, str]]:
    sid, token, svc = config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, config.TWILIO_VERIFY_SERVICE_SID
    if not (sid and token and svc):
        raise SmsError("twilio_verify_not_configured")
    return f"https://verify.twilio.com/v2/Services/{svc}", (sid, token)


def uses_remote_check() -> bool:
    """True when the provider generates and checks the code itself (Twilio Verify)."""
    return config.SMS_PROVIDER == "twilio_verify"


def start_verification(phone: str) -> None:
    base, auth = _verify_base()
    try:
        r = httpx.post(f"{base}/Verifications", data={"To": phone, "Channel": "sms"}, auth=auth, timeout=10)
    except httpx.HTTPError as e:
        raise SmsError("network") from e
    if r.status_code >= 300:
        log.error("Twilio Verify rejected start: %s", r.text[:300])
        raise SmsError(f"verify_{r.status_code}")


def check_verification(phone: str, code: str) -> bool:
    base, auth = _verify_base()
    try:
        r = httpx.post(f"{base}/VerificationCheck", data={"To": phone, "Code": code}, auth=auth, timeout=10)
    except httpx.HTTPError as e:
        raise SmsError("network") from e
    if r.status_code == 404:  # expired or already approved
        return False
    if r.status_code >= 300:
        log.error("Twilio Verify check failed: %s", r.text[:300])
        raise SmsError(f"verify_{r.status_code}")
    return r.json().get("status") == "approved"


_PROVIDERS = {"twilio": _twilio, "msg91": _msg91, "console": _console}


def send_otp(phone: str, code: str) -> None:
    fn = _PROVIDERS.get(config.SMS_PROVIDER)
    if fn is None:
        raise SmsError("unknown_provider")
    try:
        fn(phone, code)
    except httpx.HTTPError as e:
        raise SmsError("network") from e
