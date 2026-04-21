"""Integration tests for the non-streaming chat variants (/chat/poll, /chat/answer).

Both endpoints drive the same pipeline as /chat but surface chunks differently:
    * /chat/poll returns the full chunk list as JSON (for debugging / E2E harness).
    * /chat/answer returns only the final answer text + the generated SQL list.

The shared ``patched_pipeline`` fixture from tests/conftest.py swaps in a 2-stage fake
so these stay Gemini-free and fast.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


# --- /chat/poll -----------------------------------------------------------------


def test_chat_poll_returns_chunks_list(authed_client: TestClient, patched_pipeline):
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "conversation_id" in body
    assert isinstance(body["chunks"], list) and body["chunks"]
    types = [c["type"] for c in body["chunks"]]
    assert "sql_generated" in types
    assert "answer_generated" in types


def test_chat_poll_requires_session(client: TestClient, patched_pipeline):
    r = client.post(
        "/api/v1/chat/poll",
        json={"message": "x", "db_id": "california_schools"},
    )
    assert r.status_code == 401


# --- /chat/answer ---------------------------------------------------------------


def test_chat_answer_returns_answer_and_sql(authed_client: TestClient, patched_pipeline):
    r = authed_client.post(
        "/api/v1/chat/answer",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "The answer is 1."
    assert body["sql"] == ["SELECT 1 AS n"]
    assert body["conversation_id"]


def test_chat_answer_requires_session(client: TestClient, patched_pipeline):
    r = client.post(
        "/api/v1/chat/answer",
        json={"message": "x", "db_id": "california_schools"},
    )
    assert r.status_code == 401
