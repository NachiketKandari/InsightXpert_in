"""Internal endpoints for external schedulers.

``POST /api/internal/run-due-automations``:
    Body: ``{"tick_at": <unix_seconds>}``
    Header: ``X-Scheduler-Signature: hex(HMAC-SHA256(secret, body))``
    Responses:
        * 200 + ``{"ran": [...]}`` on success
        * 401 on signature mismatch
        * 503 when ``automations_enabled`` is false

Always mounted — the 503 branch is how we signal "off" to external callers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from ..automations import runner
from ..config import get_settings

log = logging.getLogger("insightxpert_api.routes.internal")

router = APIRouter(prefix="/api/internal", tags=["internal"])


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
    if not settings.automations_enabled:
        raise HTTPException(status_code=503, detail="automations disabled")

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

    batch = await runner.run_due_automations(request.app, now=tick_at)
    return {"ran": [item.model_dump() for item in batch.ran]}
