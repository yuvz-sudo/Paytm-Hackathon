import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["FAKE_NOW"] = "2026-11-14T09:30:00"
os.environ["SMS_PROVIDER"] = "console"  # never send real SMS from tests
os.environ["DEV_OTP_ECHO"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""  # tests exercise the deterministic path
os.environ["OPENAI_API_KEY"] = ""  # never spend real tokens from tests
os.environ["LLM_PROVIDER"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["SARVAM_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(autouse=True)
def no_network_news(monkeypatch):
    """Tests never fetch real news; tests that need headlines patch news._fetch themselves."""
    from app.services import news
    monkeypatch.setattr(news, "_fetch", lambda q: [])
    news._cache.clear()


@pytest.fixture(autouse=True)
def fresh_db():
    with SessionLocal() as db:
        seed(db, reset=True)
    yield


@pytest.fixture()
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def H(mid=1):
    return {"X-Merchant-Id": str(mid)}
