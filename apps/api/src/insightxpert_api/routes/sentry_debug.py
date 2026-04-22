"""Sentry smoke-test route — admin-only.

Two endpoints for verifying the Sentry wiring end-to-end:
- ``GET /api/v1/admin/sentry/ping``   → captures a message event, returns 200
- ``GET /api/v1/admin/sentry/boom``   → raises, letting the FastAPI integration
  capture an unhandled exception and bubble a 500 to the client

Both require admin. Safe to leave mounted — they reveal nothing an admin
doesn't already have.
"""

from __future__ import annotations

import sentry_sdk
from fastapi import APIRouter, Depends

from ..auth.current_user import CurrentUser, require_admin

router = APIRouter(prefix="/api/v1/admin/sentry", tags=["admin-sentry"])


@router.get("/ping")
async def ping(user: CurrentUser = Depends(require_admin)) -> dict:
    """Send a message-level event to Sentry and return OK."""
    event_id = sentry_sdk.capture_message(
        "insightxpert.sentry.ping",
        level="info",
    )
    return {"ok": True, "event_id": event_id, "dsn_configured": bool(sentry_sdk.Hub.current.client)}


@router.get("/boom")
async def boom(user: CurrentUser = Depends(require_admin)) -> dict:
    """Raise deliberately. FastApiIntegration reports this as an exception event."""
    raise RuntimeError("insightxpert.sentry.boom — deliberate test exception")
