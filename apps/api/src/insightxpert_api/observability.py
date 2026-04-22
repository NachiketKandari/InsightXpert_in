"""Process-level observable counters for the /metrics endpoint.

These are intentionally simple in-memory integers — no deps, no threads,
just monotonic counters that the /metrics route reads. The audit queue and
SSE reaper update them; the /metrics route reads them.

All counters live here so every subsystem imports from one place instead of
cross-importing.
"""

from __future__ import annotations

import threading

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

# Lock for mutation from multiple async tasks / threads.
_lock = threading.Lock()


def increment_sse_evicted(n: int = 1) -> None:
    global sse_evicted_total
    with _lock:
        sse_evicted_total += n


def increment_llm_calls(source: str, n: int = 1) -> None:
    with _lock:
        llm_calls_total[source] = llm_calls_total.get(source, 0) + n
