"""Liveness/readiness probe with background DB health checker.

Every request to ``GET /health`` returns instantly (no I/O).  A background
task pings the database every 5 seconds and atomically updates an in-memory
status struct.  Readers see either the previous or current state — never a
partially-written one — because Python's GIL guarantees reference
assignments are atomic.

The checker starts in the app ``lifespan`` so the first request already has
a warm result.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/api/v1", tags=["health"])

_DB_CHECK_TIMEOUT = 2.0  # seconds — shorter than statement_timeout (30s)
_TICK_INTERVAL = 5.0     # seconds between background DB pings


# ---------------------------------------------------------------------------
# In-memory health state — atomically replaced by the background checker.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _HealthState:
    db_reachable: bool = False
    db_latency_ms: float = 0.0


# Module-level state.  The background task creates a *new instance* on every
# tick and swaps the reference.  Python's GIL makes simple assignments
# atomic across coroutine yields, so readers always see a consistent struct
# without any lock.
_state: _HealthState = _HealthState()


# ---------------------------------------------------------------------------
# Background checker — started / stopped in the app lifespan.
# ---------------------------------------------------------------------------

def _ping_db(engine: object) -> None:
    """Synchronous DB ping — runs in a thread via asyncio.to_thread."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


async def _probe() -> tuple[bool, float]:
    """Ping the database and return ``(reachable, latency_ms)``."""
    from ..db.engine import get_engine

    t0 = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_ping_db, get_engine()),
            timeout=_DB_CHECK_TIMEOUT,
        )
        return True, round((time.monotonic() - t0) * 1000, 1)
    except (TimeoutError, Exception):
        return False, 0.0


async def run_health_checker() -> None:
    """Background task that periodically probes the database.

    Run this via ``asyncio.create_task`` in the app lifespan.  The first
    probe fires immediately so ``/health`` always has a warm answer.
    """
    global _state

    # First probe — blocks until the initial status is known.
    ok, latency = await _probe()
    _state = _HealthState(db_reachable=ok, db_latency_ms=latency)

    while True:
        try:
            await asyncio.sleep(_TICK_INTERVAL)
        except asyncio.CancelledError:
            break
        ok, latency = await _probe()
        _state = _HealthState(db_reachable=ok, db_latency_ms=latency)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/health")
async def health() -> JSONResponse:
    """Liveness + readiness probe.  Zero I/O — reads the cached status."""
    current = _state   # atomic read, no lock needed
    return JSONResponse(
        content={
            "status": "ok" if current.db_reachable else "degraded",
            "db": {
                "reachable": current.db_reachable,
                "latency_ms": current.db_latency_ms,
            },
        },
        status_code=200 if current.db_reachable else 503,
    )
