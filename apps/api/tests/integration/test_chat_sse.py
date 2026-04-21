"""Integration test for the chat SSE endpoint. Pipeline stages are replaced with fakes
so the test stays fast and deterministic (no real Gemini calls).

The ``patched_pipeline`` fixture is defined in ``tests/conftest.py`` and shared with
the chat variant (/chat/poll, /chat/answer) tests.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_chat_sse_streams_chunks_and_terminates(
    authed_client: TestClient, patched_pipeline
):
    with authed_client.stream(
        "POST",
        "/api/v1/chat",
        json={"message": "count rows", "db_id": "california_schools"},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes())
    text = body.decode()
    assert "data: [DONE]" in text
    assert '"type":"status"' in text or '"type": "status"' in text
    assert "sql_generated" in text
    assert "answer_generated" in text


def test_chat_requires_session(client: TestClient, patched_pipeline):
    r = client.post(
        "/api/v1/chat",
        json={"message": "x", "db_id": "california_schools"},
    )
    assert r.status_code == 401


def test_chat_rejects_empty_message(authed_client: TestClient, patched_pipeline):
    r = authed_client.post(
        "/api/v1/chat",
        json={"message": "", "db_id": "california_schools"},
    )
    assert r.status_code == 422
