import pytest

from app import config
from app.models import AuthSession, Merchant, OtpChallenge
from tests.conftest import H

ALL = {s: True for s in ["transactions", "customers", "ledger", "credit", "messaging"]}


def signup(client, phone="98765 11111", **over):
    r = client.post("/api/auth/request-otp", json={"phone": phone}).json()
    v = client.post("/api/auth/verify", json={"phone": phone, "otp": r["dev_otp"]})
    assert v.status_code == 200, v.text
    tok = v.json()["token"]
    return tok, {"Authorization": f"Bearer {tok}"}


def onboard_body(**over):
    b = dict(business_name="Verma General Store", owner_name="Sunil Verma", segment="kirana", city="Nagpur", language="hinglish",
             gst_registered=False, consents=ALL, sample_data=False)
    b.update(over)
    return b


# ---------------------------------------------------------------- login
@pytest.mark.parametrize("raw,norm", [("98765 43210", "+919876543210"), ("+91-9876543210", "+919876543210"), ("09876543210", "+919876543210"), ("919876543210", "+919876543210")])
def test_phone_normalisation(client, raw, norm):
    assert client.post("/api/auth/request-otp", json={"phone": raw}).json()["phone"] == norm


@pytest.mark.parametrize("bad", ["", "12345", "5876543210", "abcdefghij", "98765432101234", "+1 415 555 2671"])
def test_invalid_phone_rejected(client, bad):
    assert client.post("/api/auth/request-otp", json={"phone": bad}).status_code == 422


def test_wrong_otp_and_attempt_limit(client):
    r = client.post("/api/auth/request-otp", json={"phone": "9876522222"}).json()
    wrong = "000000" if r["dev_otp"] != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/auth/verify", json={"phone": "9876522222", "otp": wrong}).json()["detail"]["error"] == "otp_incorrect"
    # locked after 5 tries, even the right code no longer works
    assert client.post("/api/auth/verify", json={"phone": "9876522222", "otp": r["dev_otp"]}).status_code in (400, 429)


def test_otp_single_use_and_latest_only(client):
    a = client.post("/api/auth/request-otp", json={"phone": "9876533333"}).json()["dev_otp"]
    b = client.post("/api/auth/request-otp", json={"phone": "9876533333"}).json()["dev_otp"]
    if a != b:
        assert client.post("/api/auth/verify", json={"phone": "9876533333", "otp": a}).status_code == 400  # superseded
    assert client.post("/api/auth/verify", json={"phone": "9876533333", "otp": b}).status_code == 200
    assert client.post("/api/auth/verify", json={"phone": "9876533333", "otp": b}).status_code == 400  # replay


def test_otp_expires(client, monkeypatch):
    r = client.post("/api/auth/request-otp", json={"phone": "9876544444"}).json()
    monkeypatch.setenv("FAKE_NOW", "2026-11-14T10:00:00")  # > 5 minutes after 09:30
    assert client.post("/api/auth/verify", json={"phone": "9876544444", "otp": r["dev_otp"]}).json()["detail"]["error"] == "otp_expired"


def test_request_rate_limit(client):
    codes = [client.post("/api/auth/request-otp", json={"phone": "9876555555"}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_otp_and_token_are_not_stored_in_clear(client, db):
    r = client.post("/api/auth/request-otp", json={"phone": "9876566666"}).json()
    tok, _ = signup(client, "9876577777")
    assert db.query(OtpChallenge).filter(OtpChallenge.code_hash == r["dev_otp"]).count() == 0
    assert db.query(AuthSession).filter(AuthSession.token_hash == tok).count() == 0


def test_dev_otp_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "DEV_OTP_ECHO", False)
    assert "dev_otp" not in client.post("/api/auth/request-otp", json={"phone": "9876588888"}).json()


# ---------------------------------------------------------------- onboarding
def test_new_user_must_onboard_before_using_anything(client):
    _, h = signup(client)
    assert client.get("/api/auth/me", headers=h).json()["onboarded"] is False
    assert client.get("/api/briefing", headers=h).status_code == 403
    assert client.get("/api/briefing", headers=h).json()["detail"]["error"] == "onboarding_required"


def test_onboarding_happy_path_and_consents(client, db):
    _, h = signup(client)
    consents = {**ALL, "ledger": False, "credit": False}
    r = client.post("/api/onboarding", json=onboard_body(consents=consents, language="hi"), headers=h)
    assert r.status_code == 200 and r.json()["onboarded"] and r.json()["language"] == "hi"
    got = {c["scope"]: c["granted"] for c in client.get("/api/consent", headers=h).json()}
    assert got["ledger"] is False and got["credit"] is False and got["transactions"] is True
    assert client.get("/api/udhaar", headers=h).status_code == 403  # consent honoured immediately
    assert client.post("/api/onboarding", json=onboard_body(), headers=h).status_code == 409  # not twice


def test_unsent_consents_default_to_off(client):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(consents={"transactions": True}), headers=h)
    got = {c["scope"]: c["granted"] for c in client.get("/api/consent", headers=h).json()}
    assert got["transactions"] and not got["messaging"] and not got["customers"]


@pytest.mark.parametrize("patch", [
    {"business_name": "A"}, {"owner_name": ""}, {"segment": "spaceship"}, {"city": "<script>"}, {"language": "klingon"},
    {"business_name": "<b>x</b>"}, {"gst_registered": True, "gst_number": "NOTAGSTIN"}, {"consents": {"hacking": True}}, {"soundbox_id": "!!"},
])
def test_onboarding_validation(client, patch):
    _, h = signup(client)
    assert client.post("/api/onboarding", json=onboard_body(**patch), headers=h).status_code == 422


def test_valid_gstin_accepted(client):
    _, h = signup(client)
    r = client.post("/api/onboarding", json=onboard_body(gst_registered=True, gst_number="27ABCDE1234F1Z5"), headers=h)
    assert r.status_code == 200 and r.json()["gst_number"] == "27ABCDE1234F1Z5"


def test_returning_user_logs_into_same_account(client, db):
    _, h = signup(client, "9876599999")
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    before = db.query(Merchant).count()
    _, h2 = signup(client, "98765 99999")
    assert db.query(Merchant).count() == before
    assert client.get("/api/auth/me", headers=h2).json()["name"] == "Verma General Store"


def test_demo_merchant_can_log_in_with_otp(client):
    _, h = signup(client, "9876500001")
    assert client.get("/api/auth/me", headers=h).json()["name"] == "Ramesh Kirana Store"


# ---------------------------------------------------------------- isolation & sessions
def test_demo_header_disabled_in_production_mode(client, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_DEMO_HEADER", False)
    assert client.get("/api/briefing", headers=H(1)).status_code == 401
    assert client.get("/api/merchants").status_code == 404


def test_no_credentials_is_401(client):
    assert client.get("/api/briefing").status_code == 401
    assert client.get("/api/briefing", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_logout_revokes_session(client):
    _, h = signup(client)
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_users_cannot_see_each_others_data(client):
    _, ha = signup(client, "9876511110")
    _, hb = signup(client, "9876511112")
    client.post("/api/onboarding", json=onboard_body(sample_data=True), headers=ha)
    client.post("/api/onboarding", json=onboard_body(business_name="Other Shop"), headers=hb)
    assert client.get("/api/udhaar", headers=ha).json()["count"] > 0
    assert client.get("/api/udhaar", headers=hb).json()["count"] == 0


def test_expired_session_rejected(client, monkeypatch):
    _, h = signup(client)
    monkeypatch.setenv("FAKE_NOW", "2026-12-30T09:30:00")  # > 30 days
    assert client.get("/api/auth/me", headers=h).status_code == 401


# ---------------------------------------------------------------- brand-new merchant with NO data
GETS = ["/api/briefing", "/api/sales/summary?period=yesterday", "/api/sales/summary?period=today", "/api/sales/series?days=30", "/api/sales/best",
        "/api/sales/hours", "/api/stock", "/api/udhaar", "/api/customers", "/api/gst?period=last_month",
        "/api/settlements", "/api/chargebacks", "/api/fees/mdr?period=this_month", "/api/payments/verify?amount=500", "/api/credit", "/api/actions", "/api/outbox", "/api/consent", "/api/audit", "/api/items", "/api/suppliers"]


@pytest.mark.parametrize("seg", ["kirana", "salon", "other"])
def test_empty_merchant_never_crashes(client, seg):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(segment=seg, gst_registered=seg == "kirana"), headers=h)
    for path in GETS:
        r = client.get(path, headers=h)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
    for q in ["briefing", "kal ki sales", "stock", "udhaar kitna baaki hai", "gst", "loan chahiye", "reviews", "kal sales kam kyu hui",
              "order kar do", "customers", "aaj kya karna chahiye", "atta kitna bacha hai", "settlement", "payout kam kyun aaya", "chargeback", "chargeback ka proof bhejo", "UPI fee lagega?",
              "payment aaya 500", "customer ne screenshot dikhaya", "offer bhejo"]:
        r = client.post("/api/chat", json={"message": q}, headers=h)
        assert r.status_code == 200 and r.json()["reply"] and r.json()["engine"] != "error", (q, r.text[:200])


def test_empty_briefing_welcomes_instead_of_blank(client):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    b = client.get("/api/briefing", headers=h).json()
    assert b["script"] and b["empty"] is True


# ---------------------------------------------------------------- sample data + catalogue
def test_sample_data_load_and_remove(client):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(segment="sweets"), headers=h)
    assert client.get("/api/sales/summary?period=yesterday", headers=h).json()["no_data"] is True
    assert client.post("/api/onboarding/sample-data", headers=h).status_code == 200
    assert client.get("/api/sales/summary?period=yesterday", headers=h).json()["no_data"] is False
    assert client.post("/api/onboarding/sample-data", headers=h).status_code == 409  # not twice
    assert client.delete("/api/onboarding/sample-data", headers=h).status_code == 200
    assert client.get("/api/sales/summary?period=yesterday", headers=h).json()["no_data"] is True
    assert client.get("/api/items", headers=h).json() == []


def test_sample_data_removal_only_touches_own_data(client):
    _, ha = signup(client, "9876522210")
    _, hb = signup(client, "9876522211")
    for h in (ha, hb):
        client.post("/api/onboarding", json=onboard_body(sample_data=True), headers=h)
    client.delete("/api/onboarding/sample-data", headers=ha)
    assert client.get("/api/udhaar", headers=hb).json()["count"] > 0
    assert client.get("/api/udhaar", headers=H(1)).json()["count"] > 0  # demo merchant untouched


def test_cannot_remove_real_data(client):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    assert client.delete("/api/onboarding/sample-data", headers=h).status_code == 409


def test_add_supplier_and_items_then_stock_flow(client):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    sup = client.post("/api/suppliers", json={"name": "Local Wholesale", "phone": "98200 99999", "lead_time_days": 2}, headers=h)
    assert sup.status_code == 201
    assert client.post("/api/suppliers", json={"name": "Local Wholesale", "phone": "9820099999"}, headers=h).status_code == 409
    assert client.post("/api/suppliers", json={"name": "Bad", "phone": "123"}, headers=h).status_code == 422
    it = client.post("/api/items", json={"name": "Atta 5kg", "aliases": ["atta"], "unit": "bag", "price": 240, "supplier_id": sup.json()["id"], "stock_qty": 20}, headers=h)
    assert it.status_code == 201
    assert client.post("/api/items", json={"name": "atta 5KG", "price": 1}, headers=h).status_code == 409
    assert client.post("/api/items", json={"name": "X", "price": -5}, headers=h).status_code == 422
    assert client.post("/api/items", json={"name": "Y", "price": 5, "supplier_id": 9999}, headers=h).status_code == 422
    assert client.get("/api/stock", headers=h).json()["items"][0]["item"] == "Atta 5kg"
    # another merchant's supplier cannot be attached
    _, h2 = signup(client, "9876511119")
    client.post("/api/onboarding", json=onboard_body(), headers=h2)
    assert client.post("/api/items", json={"name": "Z", "price": 5, "supplier_id": sup.json()["id"]}, headers=h2).status_code == 422
    assert client.delete(f"/api/items/{it.json()['id']}", headers=h).status_code == 200
    assert client.get("/api/items", headers=h).json() == []


def test_profile_update(client):
    _, h = signup(client)
    client.post("/api/onboarding", json=onboard_body(), headers=h)
    r = client.put("/api/merchant/profile", json={"city": "Indore", "max_offer_discount_pct": 10}, headers=h)
    assert r.status_code == 200 and r.json()["city"] == "Indore"
    assert client.put("/api/merchant/profile", json={"max_offer_discount_pct": 90}, headers=h).status_code == 422


def test_sms_provider_called_and_failure_rolls_back(client, monkeypatch):
    from app import config
    from app.services import sms
    sent = []
    monkeypatch.setattr(config, "SMS_PROVIDER", "twilio")
    monkeypatch.setattr(sms, "_PROVIDERS", {"twilio": lambda p, c: sent.append((p, c))})
    r = client.post("/api/auth/request-otp", json={"phone": "9876566666"}).json()
    assert sent == [("+919876566666", r["dev_otp"])]

    def boom(p, c):
        raise sms.SmsError("twilio_401")
    monkeypatch.setitem(sms._PROVIDERS, "twilio", boom)
    bad = client.post("/api/auth/request-otp", json={"phone": "9876566666"})
    assert bad.status_code == 502
    # the earlier code still works because the failed request rolled back
    assert client.post("/api/auth/verify", json={"phone": "9876566666", "otp": r["dev_otp"]}).status_code == 200


def test_twilio_verify_mode(client, monkeypatch):
    from app import config
    from app.services import sms
    monkeypatch.setattr(config, "SMS_PROVIDER", "twilio_verify")
    started = []
    monkeypatch.setattr(sms, "start_verification", lambda p: started.append(p))
    monkeypatch.setattr(sms, "check_verification", lambda p, c: c == "123456")
    r = client.post("/api/auth/request-otp", json={"phone": "9876577777"}).json()
    assert started == ["+919876577777"] and "dev_otp" not in r
    assert client.post("/api/auth/verify", json={"phone": "9876577777", "otp": "000000"}).status_code == 400
    assert client.post("/api/auth/verify", json={"phone": "9876577777", "otp": "123456"}).status_code == 200


def test_older_clients_sending_reviews_consent_still_onboard(client):
    _, h = signup(client)
    r = client.post("/api/onboarding", json=onboard_body(consents={**ALL, "reviews": True}), headers=h)
    assert r.status_code == 200
    assert "reviews" not in {c["scope"] for c in client.get("/api/consent", headers=h).json()}
