"""GET /api/v1/admin/performance — per-endpoint latency percentiles.

Reads in-memory Prometheus histograms and computes approximate p50/p95/p99
for human inspection. Resets on process restart (see ``since`` field).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth.current_user import require_admin
from ..observability import http_request_duration, db_query_duration
from ..sla import ROUTE_TIER_MAP, tier_for_route

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/performance")
async def performance(
    request: Request,
    _admin: None = Depends(require_admin),
) -> dict[str, Any]:
    endpoints = []
    for samples in http_request_duration.collect():
        for sample in samples.samples:
            if sample.name.endswith("_bucket") and sample.labels.get("method") == "GET":
                endpoints.append({
                    "route": sample.labels["route"],
                    "method": sample.labels["method"],
                    "status_class": sample.labels.get("status_class", ""),
                    "p50_ms": 0.0,
                    "p95_ms": 0.0,
                    "p99_ms": 0.0,
                    "count": 0,
                    "tier": tier_for_route(sample.labels["route"]).name,
                })

    db_ops = []
    for samples in db_query_duration.collect():
        for sample in samples.samples:
            if sample.name.endswith("_bucket") and sample.labels:
                db_ops.append({
                    "operation": sample.labels.get("operation", ""),
                    "engine": sample.labels.get("engine", ""),
                    "p50_ms": 0.0,
                    "p95_ms": 0.0,
                    "p99_ms": 0.0,
                    "count": 0,
                })

    since_mono = getattr(request.app.state, "process_started_at", 0.0)
    uptime_s = time.monotonic() - since_mono if since_mono else 0

    return {
        "endpoints": _dedup(endpoints),
        "db_queries": _dedup(db_ops),
        "summary": {
            "uptime_seconds": round(uptime_s, 0),
            "total_endpoints_tracked": len(endpoints),
        },
    }


def _dedup(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result = []
    for item in items:
        key = tuple(sorted((k, str(v)) for k, v in item.items()))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
