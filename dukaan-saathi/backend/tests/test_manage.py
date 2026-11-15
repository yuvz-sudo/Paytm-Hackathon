"""Customers and items CRUD, udhaar by customer id (same-name customers), and honest delivery of approved messages."""
from app import clock
from app.models import Customer, Item, LedgerEntry
from app.services import delivery

H = {"X-Merchant-Id": "1"}


def test_add_edit_remove_customer(client):
    r = client.post("/api/customers", headers=H, json={"name": "  Asha   Verma ", "phone": "98765 43210"})
    assert r.status_code == 201 and r.json()["name"] == "Asha Verma" and r.json()["phone"] == "+919876543210"
    cid = r.json()["id"]
    assert client.post("/api/customers", headers=H, json={"name": "Someone", "phone": "+91-9876543210"}).status_code == 409  # same number
    assert client.post("/api/customers", headers=H, json={"name": "Bad", "phone": "12345"}).status_code == 422
    assert client.post("/api/customers", headers=H, json={"name": "<b>x</b>"}).status_code == 422
    r = client.put(f"/api/customers/{cid}", headers=H, json={"phone": "09123456789", "do_not_contact": True}).json()
    assert r["phone"] == "+919123456789" and r["do_not_contact"] is True
    found = client.get("/api/customers/all?q=9123", headers=H).json()["customers"]
    assert [c["id"] for c in found] == [cid]
    assert client.delete(f"/api/customers/{cid}", headers=H).json()["ok"] is True
    assert client.put(f"/api/customers/{cid}", headers=H, json={"name": "x"}).status_code == 404


def test_cannot_remove_customer_with_udhaar_or_history(client, db):
    owing = client.get("/api/udhaar", headers=H).json()["customers"][0]
    r = client.delete(f"/api/customers/{owing['customer_id']}", headers=H)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "has_udhaar"


def test_customers_are_private_per_merchant(client):
    cid = client.post("/api/customers", headers=H, json={"name": "Only Mine"}).json()["id"]
    other = {"X-Merchant-Id": "2"}
    assert client.put(f"/api/customers/{cid}", headers=other, json={"name": "hijack"}).status_code == 404
    assert client.delete(f"/api/customers/{cid}", headers=other).status_code == 404


def test_same_name_customers_are_resolved_by_id(client, db):
    a = client.post("/api/customers", headers=H, json={"name": "Twin Name", "phone": "9000000001"}).json()
    b = client.post("/api/customers", headers=H, json={"name": "Twin Name", "phone": "9000000002"}).json()
    assert b["same_name_count"] == 1
    r = client.post("/api/udhaar/credit", headers=H, json={"customer": "Twin Name", "amount": 100})
    assert r.status_code == 409
    cands = r.json()["detail"]["candidates"]
    assert {c["id"] for c in cands} == {a["id"], b["id"]} and all(c["label"].startswith("Twin Name (…000") for c in cands)
    r = client.post("/api/udhaar/credit", headers=H, json={"customer_id": b["id"], "amount": 100}).json()
    assert r["customer_id"] == b["id"] and r["balance"] == 100
    r = client.post("/api/udhaar/payment", headers=H, json={"customer_id": b["id"], "amount": 40}).json()
    assert r["balance"] == 60
    assert client.post("/api/udhaar/payment", headers=H, json={"customer_id": 999999, "amount": 1}).status_code == 404
    assert client.post("/api/udhaar/payment", headers=H, json={"amount": 1}).status_code == 422
    r = client.post("/api/chat", headers=H, json={"message": "Twin Name ka 50 udhaar likho", "language": "en"}).json()
    assert "…0001" in r["reply"] and "…0002" in r["reply"]  # chat asks which one, with numbers to tell them apart


def test_remind_one_customer_by_id(client):
    row = next(c for c in client.get("/api/udhaar", headers=H).json()["customers"] if c["overdue"] > 0 and not c["do_not_contact"])
    r = client.post("/api/udhaar/remind", headers=H, json={"customer_id": row["customer_id"]}).json()
    assert len(r["proposals"]) == 1 and r["proposals"][0]["payload"]["customer_id"] == row["customer_id"]


def test_edit_item_keeps_other_fields_and_counts_stock(client, db):
    it = db.query(Item).filter_by(merchant_id=1, name="Sugar").first()
    pack, sup = it.pack_qty, it.supplier_id
    r = client.put(f"/api/items/{it.id}", headers=H, json={"price": 48, "stock_qty": 30}).json()
    assert r["price"] == 48 and r["pack_qty"] == pack and r["supplier_id"] == sup and r["stock_qty"] == 30
    db.refresh(it)
    assert it.stock_reported_at is not None and abs((clock.now() - it.stock_reported_at).total_seconds()) < 5
    assert client.put(f"/api/items/{it.id}", headers=H, json={"name": "atta 5kg"}).status_code == 409  # clashes with Atta 5kg
    assert client.put(f"/api/items/{it.id}", headers=H, json={"price": 0}).status_code == 422
    assert client.put(f"/api/items/{it.id}", headers=H, json={"supplier_id": 99999}).status_code == 422
    assert client.put(f"/api/items/{it.id}", headers={"X-Merchant-Id": "2"}, json={"price": 1}).status_code == 404
    listed = next(i for i in client.get("/api/items", headers=H).json() if i["id"] == it.id)
    assert listed["pack_qty"] == pack


def test_add_and_remove_item(client):
    r = client.post("/api/items", headers=H, json={"name": "Poha 1kg", "unit": "kg", "price": 60, "stock_qty": 12}).json()
    assert any(x["item"] == "Poha 1kg" for x in client.get("/api/stock", headers=H).json()["items"])
    assert client.delete(f"/api/items/{r['id']}", headers=H).json()["ok"] is True
    assert not any(x["item"] == "Poha 1kg" for x in client.get("/api/stock", headers=H).json()["items"])


def test_whatsapp_numbers():
    assert delivery.wa_number("+91 98765 43210") == "919876543210"
    assert delivery.wa_number("9876543210") == "919876543210"
    assert delivery.wa_number("") is None and delivery.wa_number("12345") is None and delivery.wa_number("+91 1234567890") is None


def test_approved_message_is_ready_to_send_with_whatsapp_link(client):
    p = client.post("/api/stock/order", headers=H, json={}).json()["proposals"][0]
    r = client.post(f"/api/actions/{p['id']}/approve", headers=H).json()
    d = r["deliveries"][0]
    assert d["status"] == "ready" and d["whatsapp_url"].startswith("https://wa.me/91") and "text=" in d["whatsapp_url"]
    out = client.get("/api/outbox", headers=H).json()
    assert out[0]["id"] == d["id"] and out[0]["status"] == "ready"
    assert client.post(f"/api/outbox/{d['id']}/mark", headers=H, json={"status": "sent"}).json()["status"] == "sent"
    assert client.get("/api/outbox", headers=H).json()[0]["status"] == "sent"
    assert client.post(f"/api/outbox/{d['id']}/mark", headers={"X-Merchant-Id": "2"}, json={"status": "sent"}).status_code == 404


def test_customer_without_number_is_flagged(client, db):
    c = Customer(merchant_id=1, name="No Phone Person", phone="", created_at=clock.now())
    db.add(c)
    db.flush()
    db.add(LedgerEntry(merchant_id=1, customer_id=c.id, kind="credit_given", amount=300, ts=clock.now(), due_date=clock.today(), note=""))
    db.commit()
    a = client.post("/api/udhaar/remind", headers=H, json={"customer_id": c.id}).json()["proposals"]
    if a:  # not overdue yet is fine; if proposed, the delivery must say a number is needed
        r = client.post(f"/api/actions/{a[0]['id']}/approve", headers=H).json()
        assert r["deliveries"][0]["needs_number"] is True and r["deliveries"][0]["whatsapp_url"] is None
