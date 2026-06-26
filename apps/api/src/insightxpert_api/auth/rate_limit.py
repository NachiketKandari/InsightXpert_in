"""Per-IP rate limiter for auth endpoints (login, register, invite)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from ..config import get_settings

_buckets: dict[str, deque[float]] = defaultdict(lambda: deque())
_SWEEP_EVERY = 10_000
_call_count = 0


async def check_auth_rate_limit(request: Request) -> None:
    global _call_count
    settings = get_settings()
    if not settings.auth_rate_limit_enabled:
        return

    client_ip = request.client.host if request.client else "unknown"
    limit = max(1, settings.auth_rate_limit_per_minute)
    now = time.monotonic()
    bucket = _buckets[client_ip]

    while bucket and now - bucket[0] > 60:
        bucket.popleft()

    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
            headers={"Retry-After": "60"},
        )

    bucket.append(now)

    _call_count += 1
    if _call_count % _SWEEP_EVERY == 0:
        stale = [ip for ip, dq in _buckets.items() if not dq or now - dq[-1] > 120]
        for ip in stale:
            del _buckets[ip]
