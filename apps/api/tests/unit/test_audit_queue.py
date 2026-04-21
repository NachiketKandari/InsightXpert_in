"""AuditQueue: flushes on batch-size, flushes on interval."""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.asyncio
async def test_queue_flushes_on_size(fresh_db):
    from insightxpert_api.audit.queue import AuditQueue, AuditRow, reset_queue_for_tests

    reset_queue_for_tests()
    q = AuditQueue(batch_size=3, batch_interval_ms=5000)
    await q.start()
    try:
        for i in range(3):
            await q.put(AuditRow(
                user_id=None,
                method="POST",
                path=f"/api/v1/test/{i}",
                resource_type="test",
                resource_id=str(i),
                status_code=200,
                ip="127.0.0.1",
                user_agent="test",
            ))
        # Allow the drain task a moment to fire.
        for _ in range(50):
            if q.flushed_count >= 3:
                break
            await asyncio.sleep(0.02)
        assert q.flushed_count == 3
    finally:
        await q.stop()

    engine = create_engine(fresh_db)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one()
    assert n == 3


@pytest.mark.asyncio
async def test_queue_flushes_on_interval(fresh_db):
    from insightxpert_api.audit.queue import AuditQueue, AuditRow, reset_queue_for_tests

    reset_queue_for_tests()
    # Big batch size, short interval — single row must flush on the timeout.
    q = AuditQueue(batch_size=1000, batch_interval_ms=50)
    await q.start()
    try:
        await q.put(AuditRow(
            user_id="u1",
            method="POST",
            path="/api/v1/test",
            resource_type="test",
            resource_id=None,
            status_code=201,
            ip=None,
            user_agent=None,
        ))
        t0 = time.monotonic()
        while q.flushed_count < 1 and (time.monotonic() - t0) < 2.0:
            await asyncio.sleep(0.02)
        assert q.flushed_count == 1
    finally:
        await q.stop()

    engine = create_engine(fresh_db)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one()
    assert n == 1
