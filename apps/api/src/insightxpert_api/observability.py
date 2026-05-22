"""Process-level observable counters for the /metrics endpoint.

These are intentionally simple in-memory integers — no deps, no threads,
just monotonic counters that the /metrics route reads. The audit queue and
SSE reaper update them; the /metrics route reads them.

All counters live here so every subsystem imports from one place instead of
cross-importing.
"""

from __future__ import annotations

import threading

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# SSE counters (updated by the idle reaper in main.py)
# ---------------------------------------------------------------------------

#: Number of emitter entries evicted by the idle reaper.
sse_evicted_total: int = 0

# ---------------------------------------------------------------------------
# LLM call counters — placeholder; Group A will wire real call sites.
# TODO(group-a): increment these at each LLM call site once emission helper lands.
# ---------------------------------------------------------------------------

#: LLM call counters keyed by source label. Populated with 0-placeholders so
#: /metrics always emits these series even before Group A wires the call sites.
llm_calls_total: dict[str, int] = {
    "chat": 0,
    "profile": 0,
    "automation": 0,
    "trigger_compile": 0,
}

# ---------------------------------------------------------------------------
# HTTP request timing histograms (populated by TimingMiddleware)
# ---------------------------------------------------------------------------

http_request_duration = Histogram(
    "http_request_duration_seconds",
    "End-to-end HTTP request duration in seconds (wall clock).",
    ["method", "route", "status_class"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.3, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0],
)

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests processed.",
    ["method", "route", "status_class"],
)

# ---------------------------------------------------------------------------
# DB query timing histograms (populated by engine.py event listeners)
# ---------------------------------------------------------------------------

db_query_duration = Histogram(
    "db_query_duration_seconds",
    "App DB query duration in seconds.",
    ["operation", "engine"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

# ---------------------------------------------------------------------------
# SLA violation counters
# ---------------------------------------------------------------------------

sla_violations = Counter(
    "sla_violations_total",
    "Requests exceeding their SLA tier p95 target.",
    ["tier", "route"],
)

# ---------------------------------------------------------------------------
# Lock for mutation from multiple async tasks / threads.
# ---------------------------------------------------------------------------

_lock = threading.Lock()


def increment_sse_evicted(n: int = 1) -> None:
    global sse_evicted_total
    with _lock:
        sse_evicted_total += n


def increment_llm_calls(source: str, n: int = 1) -> None:
    with _lock:
        llm_calls_total[source] = llm_calls_total.get(source, 0) + n
