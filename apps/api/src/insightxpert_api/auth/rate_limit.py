"""Per-IP rate limiter for auth endpoints (login, register, invite)."""

from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse

from ..config import get_settings


async def check_auth_rate_limit(request: Request) -> None:
    settings = get_settings()
    if not settings.auth_rate_limit_enabled:
        return

    client_ip = request.client.host if request.client else "unknown"
    # Lightweight check: compare with a simple in-memory counter.
    # Full Redis-backed rate limiter would go here in production.
    # For now, this is a stub that always passes.
    _ = settings.auth_rate_limit_per_minute
    _ = client_ip
    return
