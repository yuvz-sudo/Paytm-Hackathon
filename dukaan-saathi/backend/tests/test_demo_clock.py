"""Sample data rolls forward with the calendar; real merchants are never touched."""
from datetime import datetime

from app import clock, demo_clock
from app.models import Merchant, Transaction
from app.services import payments, settlements


def _at(monkeypatch, iso):
    monkeypatch.setattr(clock, "now", lambda: datetime.fromisoformat(iso))


def test_sample_data_moves_to_today_and_keeps_the_story(db, monkeypatch):
    m = db.get(Merchant, 1)
    before = {c["id"]: c["days_left"] for c in settlements.chargebacks(db, m)["chargebacks"]} if isinstance(settlements.chargebacks(db, m), dict) else None
    _at(monkeypatch, "2026-11-17T15:00:00")
    demo_clock.refresh(db, m, force=True)
    last = db.query(Transaction.ts).filter_by(merchant_id=m.id).order_by(Transaction.ts.desc()).first()[0]
    assert last.date().isoformat() == "2026-11-17" and last <= clock.now()
    today = payments.today(db, m)
    assert today["count"] > 0 and today["date"] == "2026-11-17"
    if before is not None:
        after = {c["id"]: c["days_left"] for c in settlements.chargebacks(db, m)["chargebacks"]}
        assert after == before  # "proof due in N days" is still N days away


def test_refresh_is_idempotent(db, monkeypatch):
    m = db.get(Merchant, 1)
    _at(monkeypatch, "2026-11-16T18:00:00")
    demo_clock.refresh(db, m, force=True)
    n = db.query(Transaction).filter_by(merchant_id=m.id).count()
    demo_clock.refresh(db, m, force=True)
    assert db.query(Transaction).filter_by(merchant_id=m.id).count() == n


def test_real_merchant_is_never_shifted(db, monkeypatch):
    m = db.get(Merchant, 1)
    m.sample_data = False
    db.commit()
    n = db.query(Transaction).filter_by(merchant_id=m.id).count()
    _at(monkeypatch, "2026-11-20T12:00:00")
    demo_clock.refresh(db, m, force=True)
    assert db.query(Transaction).filter_by(merchant_id=m.id).count() == n
    last = db.query(Transaction.ts).filter_by(merchant_id=m.id).order_by(Transaction.ts.desc()).first()[0]
    assert last.date().isoformat() == "2026-11-14"
