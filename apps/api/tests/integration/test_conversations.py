"""Tests for /api/v1/conversations CRUD.

Uses the chat/poll endpoint (already driven by the shared patched_pipeline fake)
to materialize a conversation, then exercises list / get / patch / delete against it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _new_conversation(client: TestClient) -> str:
    r = client.post(
        "/api/v1/chat/poll",
        json={"message": "q", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    return r.json()["conversation_id"]


def test_list_conversations_returns_created(authed_client: TestClient, patched_pipeline):
    cid = _new_conversation(authed_client)
    r = authed_client.get("/api/v1/conversations")
    assert r.status_code == 200
    ids = [c["conversation_id"] for c in r.json()]
    assert cid in ids


def test_get_conversation_returns_detail(authed_client: TestClient, patched_pipeline):
    cid = _new_conversation(authed_client)
    r = authed_client.get(f"/api/v1/conversations/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == cid
    assert "messages" in body


def test_patch_conversation_updates_title_and_star(
    authed_client: TestClient, patched_pipeline
):
    cid = _new_conversation(authed_client)
    r = authed_client.patch(
        f"/api/v1/conversations/{cid}",
        json={"title": "hello", "starred": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "hello"
    assert body["starred"] is True


def test_delete_conversation(authed_client: TestClient, patched_pipeline):
    cid = _new_conversation(authed_client)
    r = authed_client.delete(f"/api/v1/conversations/{cid}")
    assert r.status_code == 204
    r2 = authed_client.get(f"/api/v1/conversations/{cid}")
    assert r2.status_code == 404


def test_conversations_requires_session(client: TestClient):
    r = client.get("/api/v1/conversations")
    assert r.status_code == 401
