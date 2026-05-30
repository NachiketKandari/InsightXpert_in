"""Tests for GET /api/v1/client-config (unauthenticated)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_client_config_is_public(client: TestClient):
    """Must NOT require a session — it's hit before the password gate."""
    r = client.get("/api/v1/client-config")
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["features"]["sql_executor"] is True
    assert body["config"]["features"]["model_switching"] is False
    assert body["is_admin"] is False
    assert body["org_id"] is None


def test_client_config_shape(client: TestClient):
    r = client.get("/api/v1/client-config")
    assert r.status_code == 200
    feats = r.json()["config"]["features"]
    expected = {
        "sql_executor",
        "model_switching",
        "rag_training",
        "rag_retrieval",
        "chart_rendering",
        "conversation_export",
        "agent_process_sidebar",
        "clarification_enabled",
        "stats_context_injection",
        "onboarding_enabled",
    }
    assert set(feats.keys()) == expected
