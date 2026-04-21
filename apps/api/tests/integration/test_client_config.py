"""Tests for GET /api/v1/client-config (unauthenticated)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_client_config_is_public(client: TestClient):
    """Must NOT require a session — it's hit before the password gate."""
    r = client.get("/api/v1/client-config")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "0.1.0"
    assert body["features"]["sql_runner"] is True
    assert body["features"]["upload"] is True
    assert body["features"]["voice"] is False


def test_client_config_shape(client: TestClient):
    r = client.get("/api/v1/client-config")
    assert r.status_code == 200
    feats = r.json()["features"]
    expected = {
        "sql_runner",
        "upload",
        "profile_editor",
        "voice",
        "ollama",
        "automations",
        "admin",
        "insights",
        "notifications",
    }
    assert set(feats.keys()) == expected
