"""SLA tier definitions and route-to-tier mapping.

Tiers are immutable dataclasses. The route map uses first-match-wins prefix
matching so that /api/v1/admin/* captures all admin sub-routes without
enumerating every path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SLATier:
    name: str
    p95_target_ms: int
    p99_target_ms: int


CRITICAL = SLATier("critical", p95_target_ms=300, p99_target_ms=500)
STANDARD = SLATier("standard", p95_target_ms=500, p99_target_ms=1000)
BACKGROUND = SLATier("background", p95_target_ms=2000, p99_target_ms=5000)

# (prefix, tier) — first match wins. Order matters: longer/more-specific
# prefixes must come before shorter prefixes that would also match.
ROUTE_TIER_MAP: list[tuple[str, SLATier]] = [
    # -- critical (page-reload hot path) ---------------------------------
    ("/api/v1/auth/me", CRITICAL),
    ("/api/v1/health", CRITICAL),
    ("/api/v1/conversations", CRITICAL),
    # -- standard (user-facing, I/O-bound) --------------------------------
    ("/api/v1/databases", STANDARD),
    ("/api/v1/client-config", STANDARD),
    ("/api/v1/chat", STANDARD),
    ("/api/v1/connections", STANDARD),
    ("/api/v1/sql", STANDARD),
    ("/api/v1/feedback", STANDARD),
    ("/api/v1/config", STANDARD),
    ("/api/v1/notifications", STANDARD),
    ("/api/v1/automations", STANDARD),
    ("/api/v1/public", STANDARD),
    # -- background (admin / internal) -----------------------------------
    ("/api/v1/admin", BACKGROUND),
    ("/api/internal", BACKGROUND),
]


def tier_for_route(route: str) -> SLATier:
    """Return the SLA tier for *route* (e.g. ``/api/v1/conversations``).

    Falls back to STANDARD for unmatched routes.
    """
    for prefix, tier in ROUTE_TIER_MAP:
        if route.startswith(prefix):
            return tier
    return STANDARD
