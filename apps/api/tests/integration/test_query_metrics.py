"""B3 Task 4 — query_metrics row lands per chat turn + /feedback updates thumbs."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def test_query_metrics_row_created_after_chat_turn(
    authed_client: TestClient, patched_pipeline, fresh_db
):
    """POST /chat/poll should schedule a BackgroundTask that writes query_metrics."""
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count the rows please", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    convo_id = r.json()["conversation_id"]

    # BackgroundTasks fire after the response is returned — give the runtime a
    # tiny grace window before querying.
    engine = create_engine(fresh_db)
    deadline = time.monotonic() + 3.0
    rows: list = []
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT conversation_id, db_id, agent_mode, question, thumbs, "
                "final_sql, duration_ms FROM query_metrics "
                "WHERE conversation_id = :c"
            ), {"c": convo_id}).fetchall()
        if rows:
            break
        time.sleep(0.05)

    assert len(rows) == 1
    row = rows[0]
    assert row.conversation_id == convo_id
    assert row.db_id == "california_schools"
    assert row.agent_mode is None  # agent_mode not set => legacy pipeline path
    assert row.question == "count the rows please"
    assert row.thumbs is None
    # The patched pipeline emits sql_generated with 'SELECT 1 AS n' — our
    # _extract_metrics_from_chunks reads sql_generated chunks.
    assert row.final_sql == "SELECT 1 AS n"
    assert row.duration_ms is not None


def test_thumbs_update_from_feedback(
    authed_client: TestClient, patched_pipeline, fresh_db
):
    """After a chat turn, POST /feedback should flip the most-recent row's thumbs."""
    # First drive a chat turn so a query_metrics row exists.
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "hello", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    convo_id = r.json()["conversation_id"]

    engine = create_engine(fresh_db)
    # Wait for the background-scheduled insert to land.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(*) FROM query_metrics WHERE conversation_id = :c"
            ), {"c": convo_id}).scalar_one()
        if n:
            break
        time.sleep(0.05)
    assert n == 1

    # Thumbs up.
    resp = authed_client.post(
        "/api/v1/feedback",
        json={
            "conversation_id": convo_id,
            "message_id": "m1",
            "feedback": True,
        },
    )
    assert resp.status_code == 200

    with engine.connect() as conn:
        thumbs = conn.execute(text(
            "SELECT thumbs FROM query_metrics WHERE conversation_id = :c"
        ), {"c": convo_id}).scalar_one()
    assert thumbs == "up"

    # Thumbs down flips it.
    resp2 = authed_client.post(
        "/api/v1/feedback",
        json={
            "conversation_id": convo_id,
            "message_id": "m1",
            "feedback": False,
        },
    )
    assert resp2.status_code == 200
    with engine.connect() as conn:
        thumbs = conn.execute(text(
            "SELECT thumbs FROM query_metrics WHERE conversation_id = :c"
        ), {"c": convo_id}).scalar_one()
    assert thumbs == "down"

    # Clearing (None) resets it.
    resp3 = authed_client.post(
        "/api/v1/feedback",
        json={
            "conversation_id": convo_id,
            "message_id": "m1",
            "feedback": None,
        },
    )
    assert resp3.status_code == 200
    with engine.connect() as conn:
        thumbs = conn.execute(text(
            "SELECT thumbs FROM query_metrics WHERE conversation_id = :c"
        ), {"c": convo_id}).scalar_one()
    assert thumbs is None
