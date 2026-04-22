"""Tests for the /metrics Prometheus endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test 1: Endpoint responds with 200 and text/plain content-type.
# ---------------------------------------------------------------------------

def test_metrics_returns_200_text_plain(fresh_db):
    """GET /metrics returns 200 with a text/plain content-type."""
    from insightxpert_api.main import create_app
    with TestClient(create_app()) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Test 2: Response body contains the expected metric names.
# ---------------------------------------------------------------------------

def test_metrics_contains_expected_metric_names(fresh_db):
    """GET /metrics body contains all required metric series names."""
    from insightxpert_api.main import create_app
    with TestClient(create_app()) as client:
        resp = client.get("/metrics")
    body = resp.text

    expected = [
        "audit_queue_depth",
        "audit_overflow_total",
        "sse_active_emitters",
        "sse_evicted_total",
        "llm_calls_total",
    ]
    for name in expected:
        assert name in body, f"Expected metric '{name}' not found in /metrics output"


# ---------------------------------------------------------------------------
# Test 3: audit_overflow_total counter increments after triggering overflow.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_overflow_counter_increments(fresh_db):
    """After audit queue overflow events the /metrics counter reflects them."""
    from insightxpert_api.audit.queue import get_queue, reset_queue_for_tests, _QUEUE_MAXSIZE, AuditRow
    from insightxpert_api.main import create_app

    # Reset the singleton so we get a fresh queue.
    reset_queue_for_tests()
    q = get_queue()

    # Fill and overflow by 5.
    for i in range(_QUEUE_MAXSIZE + 5):
        await q.put(AuditRow(
            user_id="u1",
            method="POST",
            path="/api/v1/test",
            resource_type="test",
            resource_id=str(i),
            status_code=200,
            ip="127.0.0.1",
            user_agent="pytest",
        ))

    # The counter on the queue object should reflect the overflow.
    assert q.overflow_total == 5

    # The /metrics endpoint should reflect the same value since the singleton
    # is shared within the test process.
    with TestClient(create_app()) as client:
        resp = client.get("/metrics")
    body = resp.text
    assert "audit_overflow_total" in body

    # Find the counter line and verify the value is >= 5.
    for line in body.splitlines():
        if line.startswith("audit_overflow_total") and not line.startswith("#"):
            value = float(line.split()[-1])
            assert value >= 5, f"Expected audit_overflow_total >= 5, got {value}"
            break

    # Cleanup: reset so other tests get a fresh queue.
    reset_queue_for_tests()
