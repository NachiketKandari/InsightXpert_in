"""GET /metrics — Prometheus text exposition format.

Exposes process-level and application-level metrics for scraping.

TODO-SECURITY: This endpoint has NO authentication. In production it MUST be
firewalled (e.g. only reachable from the internal network / VPC) or protected
by an internal-only header check (e.g. ``X-Metrics-Secret: <token>``) before
being exposed to the public internet.
"""

from __future__ import annotations

import resource
import time

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from prometheus_client import generate_latest, REGISTRY

from ..audit.queue import get_queue as _get_audit_queue
from ..observability import llm_calls_total, sse_evicted_total

router = APIRouter(tags=["metrics"])


def _gauge(name: str, value: float | int, help_text: str = "") -> str:
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    lines.append(f"{name} {value}")
    return "\n".join(lines)


def _counter(name: str, value: float | int, help_text: str = "", labels: dict[str, str] | None = None) -> str:
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} counter")
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return "\n".join(lines)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    """Prometheus text format metrics endpoint.

    No authentication on this endpoint — see TODO-SECURITY note at module top.
    """
    audit_q = _get_audit_queue()

    sse_emitters = getattr(request.app.state, "user_notification_emitters", {})

    # --- process metrics (best-effort; skip if unavailable) -----------------
    try:
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux ru_maxrss is in KB; on macOS it's in bytes.
        import sys
        if sys.platform == "linux":
            rss_bytes *= 1024
    except Exception:  # noqa: BLE001
        rss_bytes = 0

    # Approximate open file count (best-effort).
    try:
        import os
        open_files = len(os.listdir("/proc/self/fd"))
    except Exception:  # noqa: BLE001
        open_files = 0

    # Build the response body line by line.
    sections: list[str] = []

    # Audit queue metrics.
    sections.append(_gauge(
        "audit_queue_depth",
        audit_q.queue_depth,
        "Current number of rows waiting in the audit queue.",
    ))
    sections.append(_counter(
        "audit_overflow_total",
        audit_q.overflow_total,
        "Total audit rows dropped due to queue overflow (maxsize=5000).",
    ))

    # SSE metrics.
    sections.append(_gauge(
        "sse_active_emitters",
        len(sse_emitters),
        "Number of per-user SSE notification emitters currently registered.",
    ))
    sections.append(_counter(
        "sse_evicted_total",
        sse_evicted_total,
        "Total SSE emitters evicted by the idle reaper task.",
    ))

    # LLM call counters — placeholder; Group A will populate call sites.
    # NOTE: values are 0 until the unified LLM emission helper (Phase 1.2) lands.
    llm_help_emitted = False
    for source, count in llm_calls_total.items():
        line_parts = []
        if not llm_help_emitted:
            line_parts.append("# HELP llm_calls_total Total LLM API calls by source (chat|profile|automation|trigger_compile). NOTE: populated by Phase 1.2 emission helper; currently 0 placeholders.")
            line_parts.append("# TYPE llm_calls_total counter")
            llm_help_emitted = True
        line_parts.append(f'llm_calls_total{{source="{source}"}} {count}')
        sections.append("\n".join(line_parts))

    # Process metrics (best-effort).
    if rss_bytes:
        sections.append(_gauge(
            "process_resident_memory_bytes",
            rss_bytes,
            "Resident memory size in bytes (from getrusage).",
        ))
    if open_files:
        sections.append(_gauge(
            "process_open_fds",
            open_files,
            "Approximate number of open file descriptors.",
        ))

    # Append prometheus_client histograms (handles bucket serialization
    # correctly — cumulative counts, +Inf, _sum/_count, type declarations).
    try:
        sections.append(generate_latest(REGISTRY).decode("utf-8").rstrip("\n"))
    except Exception:  # noqa: BLE001
        pass

    # Prometheus expects the body to end with a newline.
    body = "\n\n".join(sections) + "\n"
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
