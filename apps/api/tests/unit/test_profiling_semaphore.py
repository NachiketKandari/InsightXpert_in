"""Phase 1.4 — profile concurrency + per-user daily cap."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_profile_semaphore_caps_concurrency() -> None:
    """Two tasks acquire; third waits until one releases."""
    from insightxpert_api.profiling.runner import (
        _profile_semaphore,
        _reset_profile_semaphore,
    )

    _reset_profile_semaphore(2)
    sem = _profile_semaphore()

    # Drain the 2 permits.
    await sem.acquire()
    await sem.acquire()

    # Third acquire must NOT complete within a short timeout.
    acquired = False

    async def _try_acquire() -> None:
        nonlocal acquired
        await sem.acquire()
        acquired = True

    task = asyncio.create_task(_try_acquire())
    await asyncio.sleep(0.05)
    assert acquired is False

    # Release one — the waiting task proceeds.
    sem.release()
    await asyncio.sleep(0.05)
    assert acquired is True

    # Cleanup.
    sem.release()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


def test_per_user_profile_cap_returns_429(user_client, monkeypatch) -> None:
    """10th profile run succeeds; 11th returns 429 with reset-time detail."""
    from sqlalchemy import insert

    from insightxpert_api.db.engine import get_engine
    from insightxpert_api.metrics.table import query_metrics

    client, user = user_client

    # Seed 10 recent profile-source rows for this user. We bypass the LLM
    # by writing directly; the route's SELECT counts these.
    import time
    import uuid

    engine = get_engine()
    now = int(time.time())
    with engine.begin() as conn:
        for i in range(10):
            conn.execute(
                insert(query_metrics).values(
                    id=uuid.uuid4().hex,
                    user_id=user.id,
                    conversation_id=f"c{i}",
                    db_id="d1",
                    question="[profile]",
                    final_sql=None,
                    agent_mode=None,
                    tokens_in=1,
                    tokens_out=1,
                    duration_ms=0,
                    thumbs=None,
                    stage_timings_json=None,
                    agent_trace_summary_json=None,
                    created_at=now - i,
                    source="profile",
                    provider="gemini",
                    model="gemini-2.5-flash",
                    cost_usd=0.001,
                    pricing_version="2026-04-24-v1",
                    source_ref_id="d1",
                )
            )

    # Seed a bundled-ish database row so the resolve step returns a ref.
    # The DB doesn't need to exist on disk — we hit the cap *before* the
    # schema stage runs. Actually the route does resolve BEFORE the cap
    # check, so we need a live DB file. Use a tmp sqlite file + upload
    # path indirection is overkill; instead point at any existing bundled
    # sqlite that resolve() will accept. Simplest: upload a tiny sqlite.
    import io
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        conn = sqlite3.connect(f.name)
        conn.execute("CREATE TABLE x (id INTEGER)")
        conn.commit()
        conn.close()
        tmpfile = f.name

    with open(tmpfile, "rb") as fh:
        data = fh.read()
    upload = client.post(
        "/api/v1/databases/upload",
        data={"db_id": "mini_profile_test"},
        files={"file": ("mini.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    assert upload.status_code in (200, 201), upload.text
    uploaded_db_id = upload.json()["db_id"]

    # Any LLM flag on → cap enforced. Use confirmed=true so the request
    # goes into the run branch (past the cost-gate short-circuit).
    resp = client.post(
        f"/api/v1/databases/{uploaded_db_id}/profile",
        json={"with_summaries": True, "confirmed": True},
    )
    assert resp.status_code == 429, resp.text
    body = resp.json()
    assert "profile_quota_exceeded" in str(body.get("detail", ""))
