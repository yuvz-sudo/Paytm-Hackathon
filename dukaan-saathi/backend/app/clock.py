"""Single source of 'now'. All timestamps are naive IST so the demo is timezone-proof."""
import os
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> datetime:
    fake = os.getenv("FAKE_NOW")  # e.g. 2026-11-14T09:00:00 for deterministic tests
    if fake:
        return datetime.fromisoformat(fake)
    return datetime.now(IST).replace(tzinfo=None)


def today() -> date:
    return now().date()


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)
