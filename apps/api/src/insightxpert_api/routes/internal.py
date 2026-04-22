"""Internal endpoints for external schedulers.

``POST /api/internal/run-due-automations``:
    Body: ``{"tick_at": <unix_seconds>}``
    Header: ``X-Scheduler-Signature: hex(HMAC-SHA256(secret, body))``
    Responses:
        * 200 + ``{"ran": [...]}`` on success
        * 401 on signature mismatch or stale ``tick_at`` (>5min drift)
        * 503 when ``automations_enabled`` is false OR
          ``automations_scheduler_mode != 'external'`` (prevents the embedded
          scheduler + an external cron both firing the same batch)

Always mounted — the 503 branch is how we signal "off" to external callers.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Header, HTTPException, Request

from ..automations import runner
from ..config import get_settings
from ..logging import get_logger

log = get_logger("routes.internal")

router = APIRouter(prefix="/api/internal", tags=["internal"])

# Max drift between ``tick_at`` and server clock. A valid HMAC captured from
# the wire can otherwise be replayed indefinitely; 5 minutes is loose enough
# to tolerate clock skew but tight enough that a replay attacker can only
# fire one extra batch at most.
_TICK_FRESHNESS_SECONDS = 300


def _constant_time_verify(secret: str, body: bytes, signature_hex: str) -> bool:
    if not secret:
        return False
    digest = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    try:
        return hmac.compare_digest(digest, signature_hex.lower())
    except Exception:  # noqa: BLE001
        return False


@router.post("/run-due-automations")
async def run_due_automations_endpoint(
    request: Request,
    x_scheduler_signature: str | None = Header(default=None),
):
    settings = get_settings()
    # Feature flag first. An unauthenticated probe getting 503 is acceptable
    # and mirrors the previous behavior.
    if not settings.automations_enabled:
        raise HTTPException(status_code=503, detail="automations disabled")
    # Double-run guard: if the embedded scheduler is running in-process, the
    # external endpoint must not also fire batches (MF4).
    if settings.automations_scheduler_mode != "external":
        raise HTTPException(
            status_code=503,
            detail=(
                "scheduler mode is not 'external'; the embedded scheduler "
                "runs in-process. Set AUTOMATIONS_SCHEDULER_MODE=external "
                "to enable this endpoint."
            ),
        )

    body = await request.body()
    if not x_scheduler_signature:
        raise HTTPException(status_code=401, detail="missing signature")
    if not _constant_time_verify(
        settings.automations_scheduler_secret, body, x_scheduler_signature
    ):
        raise HTTPException(status_code=401, detail="invalid signature")

    # Parse body
    import json as _json

    tick_at: int | None = None
    if body:
        try:
            parsed = _json.loads(body)
            if isinstance(parsed, dict):
                tick_at = parsed.get("tick_at")
        except _json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid json body")

    # Replay protection: reject stale tick_at. A valid signature replayed
    # from hours ago must not re-fire the batch.
    if tick_at is not None:
        try:
            tick_int = int(tick_at)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="tick_at must be int")
        server_now = int(time.time())
        drift = abs(server_now - tick_int)
        if drift > _TICK_FRESHNESS_SECONDS:
            log.warning(
                "scheduler.stale_tick",
                tick_at=tick_int,
                server_now=server_now,
                drift_seconds=drift,
            )
            raise HTTPException(status_code=401, detail="tick_at too stale")

    batch = await runner.run_due_automations(request.app, now=tick_at)
    return {"ran": [item.model_dump() for item in batch.ran]}
