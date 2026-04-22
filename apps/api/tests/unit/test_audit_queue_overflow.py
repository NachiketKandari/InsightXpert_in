"""Tests for audit queue maxsize cap and overflow counter."""

from __future__ import annotations

import asyncio

import pytest

from insightxpert_api.audit.queue import AuditQueue, AuditRow, _QUEUE_MAXSIZE


def _row(n: int = 0) -> AuditRow:
    return AuditRow(
        user_id="u1",
        method="POST",
        path=f"/api/v1/test/{n}",
        resource_type="test",
        resource_id=str(n),
        status_code=200,
        ip="127.0.0.1",
        user_agent="pytest",
    )


# ---------------------------------------------------------------------------
# Test 1: Queue is capped at maxsize; items beyond the cap are dropped.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_does_not_exceed_maxsize():
    """The queue's qsize never exceeds _QUEUE_MAXSIZE even when many rows are enqueued."""
    q = AuditQueue(batch_size=50, batch_interval_ms=200)
    # Do NOT start the drain task so the queue fills up cleanly.

    # Enqueue maxsize rows — all should fit.
    for i in range(_QUEUE_MAXSIZE):
        await q.put(_row(i))

    assert q._queue.qsize() == _QUEUE_MAXSIZE

    # One more row should overflow and NOT increase qsize.
    await q.put(_row(_QUEUE_MAXSIZE + 1))

    assert q._queue.qsize() == _QUEUE_MAXSIZE  # still at cap


# ---------------------------------------------------------------------------
# Test 2: overflow_total counter increments on each dropped row.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overflow_counter_increments():
    """overflow_total increments each time a row is dropped due to queue full."""
    q = AuditQueue(batch_size=50, batch_interval_ms=200)

    # Fill to capacity.
    for i in range(_QUEUE_MAXSIZE):
        await q.put(_row(i))

    assert q.overflow_total == 0

    # Overflow by 3.
    for i in range(3):
        await q.put(_row(_QUEUE_MAXSIZE + i))

    assert q.overflow_total == 3
