"""Liveness/readiness probe with DB connectivity check.

The DB check result is cached for 5 seconds to avoid hammering the database
with connection checks on every health poll (the frontend hits this every
15-120s).
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/api/v1", tags=["health"])

_DB_CHECK_TIMEOUT = 2.0  # seconds — much shorter than statement_timeout (30s)
_CACHE_TTL = 5.0  # seconds — skip the DB round-trip for rapid re-polls

_cache: tuple[bool, float, float] | None = None  # (reachable, latency_ms, timestamp)


@router.get("/health")
async def health() -> JSONResponse:
    global _cache

    db_ok = True
    db_latency_ms = 0.0

    now = time.monotonic()
    if _cache is not None and now - _cache[2] < _CACHE_TTL:
        db_ok, db_latency_ms, _ = _cache
    else:
        try:
            from ..db.engine import get_engine

            t0 = time.monotonic()
            await asyncio.wait_for(
                asyncio.to_thread(_check_db, get_engine()),
                timeout=_DB_CHECK_TIMEOUT,
            )
            db_latency_ms = round((time.monotonic() - t0) * 1000, 1)
        except (TimeoutError, Exception):  # noqa: BLE001
            db_ok = False
            db_latency_ms = 0.0

        _cache = (db_ok, db_latency_ms, now)

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
