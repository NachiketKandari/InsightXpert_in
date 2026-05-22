#!/usr/bin/env python3
"""Benchmark InsightXpert.ai API endpoints against SLA targets.

Usage:
    BENCHMARK_SESSION="<ix_session cookie value>" python scripts/benchmark.py
    BENCHMARK_BASE_URL="http://localhost:8080" BENCHMARK_SESSION="..." python scripts/benchmark.py

Requires a running server and a valid session cookie (from browser dev tools).
The session cookie is needed for auth-gated endpoints like /api/v1/conversations.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from dataclasses import dataclass

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL: str = os.getenv("BENCHMARK_BASE_URL", "http://localhost:8080")
SESSION: str = os.getenv("BENCHMARK_SESSION", "")
WARMUP: int = int(os.getenv("BENCHMARK_WARMUP", "3"))
MEASURE: int = int(os.getenv("BENCHMARK_MEASURE", "20"))


@dataclass(frozen=True)
class Target:
    method: str
    path: str
    tier: str  # critical | standard | background
    p95_target_ms: int


TARGETS: list[Target] = [
    Target("GET", "/api/v1/health", "critical", 300),
    Target("GET", "/api/v1/auth/me", "critical", 300),
    Target("GET", "/api/v1/conversations", "critical", 300),
    Target("GET", "/api/v1/databases", "standard", 500),
    Target("GET", "/api/v1/client-config", "standard", 500),
]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def percentile(sorted_values: list[float], pct: float) -> float:
    """Compute the *pct*-th percentile from sorted values using linear interpolation."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_values):
        return sorted_values[f] * (1 - c) + sorted_values[f + 1] * c
    return sorted_values[f]


def benchmark(target: Target, client: httpx.Client) -> dict:
    url = f"{BASE_URL}{target.path}"
    cookies = {"ix_session": SESSION} if SESSION else {}

    # Warmup
    for _ in range(WARMUP):
        try:
            client.request(target.method, url, cookies=cookies)
        except Exception:  # noqa: BLE001
            pass

    # Measurement
    times: list[float] = []
    for _ in range(MEASURE):
        try:
            t0 = time.monotonic()
            resp = client.request(target.method, url, cookies=cookies)
            elapsed = (time.monotonic() - t0) * 1000
            times.append(elapsed)
        except Exception:  # noqa: BLE001
            pass

    if not times:
        return {
            "endpoint": f"{target.method} {target.path}",
            "p50_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
            "mean_ms": 0,
            "requests": 0,
            "tier": target.tier,
            "p95_target_ms": target.p95_target_ms,
            "p95_pass": False,
            "error": "all requests failed",
        }

    sorted_times = sorted(times)
    p95 = percentile(sorted_times, 95)
    return {
        "endpoint": f"{target.method} {target.path}",
        "p50_ms": round(percentile(sorted_times, 50), 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(percentile(sorted_times, 99), 1),
        "min_ms": round(min(times), 1),
        "max_ms": round(max(times), 1),
        "mean_ms": round(statistics.mean(times), 1),
        "requests": len(times),
        "tier": target.tier,
        "p95_target_ms": target.p95_target_ms,
        "p95_pass": p95 <= target.p95_target_ms,
    }


def run() -> int:
    if not SESSION:
        print(
            "ERROR: BENCHMARK_SESSION env var is required.\n"
            "  Export it from your browser's ix_session cookie value.\n"
            "  Example: BENCHMARK_SESSION='ImNvb2tpZS12YWx1ZSI.Z...' python scripts/benchmark.py",
            file=sys.stderr,
        )
        return 2

    with httpx.Client(timeout=30) as client:
        results = [benchmark(t, client) for t in TARGETS]

    # Table
    header = f"{'ENDPOINT':<38} {'p50':>7} {'p95':>7} {'p99':>7} {'MIN':>7} {'MAX':>7} {'MEAN':>7}  SLA"
    print(header)
    print("-" * len(header))
    all_pass = True
    for r in results:
        status = "PASS" if r["p95_pass"] else "FAIL"
        if "error" in r:
            status = "ERR"
            all_pass = False
        elif not r["p95_pass"]:
            all_pass = False
        print(
            f"{r['endpoint']:<38} "
            f"{r['p50_ms']:>6.0f}ms "
            f"{r['p95_ms']:>6.0f}ms "
            f"{r['p99_ms']:>6.0f}ms "
            f"{r['min_ms']:>6.0f}ms "
            f"{r['max_ms']:>6.0f}ms "
            f"{r['mean_ms']:>6.0f}ms  "
            f"{status} ({r['tier']} p95<{r['p95_target_ms']}ms)"
        )

    print()
    if all_pass:
        print("All endpoints passed their SLA targets.")
    else:
        print("Some endpoints FAILED their SLA targets. Review above.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(run())
