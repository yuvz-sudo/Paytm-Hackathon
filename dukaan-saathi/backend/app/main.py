from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse

from . import config
from .api.account import router as account_router
from .api.routes import router
from .api.voice import router as voice_router
from .api.manage import router as manage_router
from .db import Base, SessionLocal, engine
from .models import Merchant

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(Merchant).count() == 0:
            from .seed import seed
            seed(db, reset=False)
        # the Reviews section was removed: retire review-reply drafts still waiting for approval
        from .models import Action
        db.query(Action).filter(Action.kind == "review_reply", Action.status == "pending").update({"status": "expired"}, synchronize_session=False)
        db.commit()
        from . import demo_clock
        for m in db.query(Merchant).filter_by(sample_data=True):
            demo_clock.refresh(db, m, force=True)
    yield


app = FastAPI(title="Dukaan Saathi API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(account_router)
app.include_router(router)
app.include_router(voice_router)
app.include_router(manage_router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logging.getLogger("dukaan").exception("unhandled: %s", exc)
    return JSONResponse({"detail": {"error": "internal_error"}}, status_code=500)


# Serve the built React app (frontend/dist) from the same origin, so one service hosts everything.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/") or path == "api":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        f = (_DIST / path).resolve()
        if path and f.is_file() and _DIST in f.parents:
            return FileResponse(f)
        return FileResponse(_DIST / "index.html")
