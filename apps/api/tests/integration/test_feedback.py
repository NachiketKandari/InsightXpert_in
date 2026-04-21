"""Tests for POST /api/v1/feedback."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_feedback_happy_path(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/feedback",
        json={
            "conversation_id": "c1",
            "message_id": "m1",
            "feedback": True,
            "comment": "helpful",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_feedback_accepts_null(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/feedback",
        json={"conversation_id": "c1", "message_id": "m1", "feedback": None},
    )
    assert r.status_code == 200


def test_feedback_requires_session(client: TestClient):
    r = client.post(
        "/api/v1/feedback",
        json={"conversation_id": "c1", "message_id": "m1", "feedback": False},
    )
    assert r.status_code == 401
