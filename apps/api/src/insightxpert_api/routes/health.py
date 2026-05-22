"""Liveness/readiness probe with DB connectivity check."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/api/v1", tags=["health"])

_DB_CHECK_TIMEOUT = 2.0  # seconds — much shorter than statement_timeout (30s)


@router.get("/health")
async def health() -> JSONResponse:
    db_ok = True
    db_latency_ms = 0.0

    try:
        from ..db.engine import get_engine

        t0 = time.monotonic()
        await asyncio.to_thread(_check_db, get_engine())
        db_latency_ms = round((time.monotonic() - t0) * 1000, 1)
    except Exception:  # noqa: BLE001
        db_ok = False

    return JSONResponse(
        content={
            "status": "ok" if db_ok else "degraded",
            "db": {
                "reachable": db_ok,
                "latency_ms": db_latency_ms,
            },
        },
        status_code=200 if db_ok else 503,
    )


def _check_db(engine: object) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
