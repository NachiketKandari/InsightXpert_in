"""ASGI middleware that records per-route HTTP request duration histograms.

Registered as the outermost middleware in the stack so it captures true
end-to-end wall-clock time including all downstream middleware (CORS, GZip,
Audit) and the route handler itself.
"""

from __future__ import annotations

import time
from typing import Callable

from ..logging import get_logger
from ..observability import http_request_duration, http_requests_total, sla_violations
from ..sla import tier_for_route

# Paths excluded from timing to avoid noise and infinite recursion.
_SKIP_PREFIXES = ("/metrics",)

log = get_logger("middleware.timing")


class TimingMiddleware:
    """Pure ASGI middleware — no thread-pool hop, unlike BaseHTTPMiddleware."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path.startswith(_SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code: int | None = None

        async def _send(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed = time.monotonic() - start
            try:
                route = scope.get("route", {})
                route_path: str = route.path if hasattr(route, "path") else path  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                route_path = path

            method = scope.get("method", "UNKNOWN")
            sc = _status_class(status_code or 0)

            try:
                http_request_duration.labels(
                    method=method, route=route_path, status_class=sc
                ).observe(elapsed)
                http_requests_total.labels(
                    method=method, route=route_path, status_class=sc
                ).inc()

                tier = tier_for_route(route_path)
                if elapsed > (tier.p95_target_ms / 1000):
                    sla_violations.labels(
                        tier=tier.name, route=route_path
                    ).inc()
            except Exception:  # noqa: BLE001
                log.warning(
                    "timing.record_failed",
                    route=route_path,
                    method=method,
                    exc_info=True,
                )


def _status_class(code: int) -> str:
    if 200 <= code < 300:
        return "2xx"
    if 300 <= code < 400:
        return "3xx"
    if 400 <= code < 500:
        return "4xx"
    if 500 <= code < 600:
        return "5xx"
    return "???"
