"""Tests for single-prompt threshold endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_get_threshold_requires_auth(client: TestClient):
    """GET /api/v1/config/threshold rejects unauthenticated clients with 401."""
    resp = client.get("/api/v1/config/threshold")
    assert resp.status_code == 401


def test_post_threshold_requires_auth(client: TestClient):
    """POST /api/v1/config/threshold rejects unauthenticated clients with 401."""
    resp = client.post("/api/v1/config/threshold", json={"threshold": 10})
    assert resp.status_code == 401


def test_get_threshold_happy_path(user_client):
    """GET /api/v1/config/threshold returns current threshold (default 25) for authenticated users."""
    client, _ = user_client
    resp = client.get("/api/v1/config/threshold")
    assert resp.status_code == 200
    assert resp.json() == {"threshold": 25}


def test_post_threshold_rejects_non_admin(user_client):
    """POST /api/v1/config/threshold rejects non-admin users with 403."""
    client, _ = user_client
    resp = client.post("/api/v1/config/threshold", json={"threshold": 15})
    assert resp.status_code == 403


def test_post_threshold_happy_path(admin_client):
    """POST /api/v1/config/threshold allows admins to update the threshold."""
    client, _ = admin_client

    # 1. Update threshold
    resp = client.post("/api/v1/config/threshold", json={"threshold": 15})
    assert resp.status_code == 200
    assert resp.json() == {"threshold": 15}

    # 2. Get to verify update took effect
    resp = client.get("/api/v1/config/threshold")
    assert resp.status_code == 200
    assert resp.json() == {"threshold": 15}

    # 3. Clean up (reset back to 25)
    resp = client.post("/api/v1/config/threshold", json={"threshold": 25})
    assert resp.status_code == 200
    assert resp.json() == {"threshold": 25}


def test_post_threshold_invalid_values(admin_client):
    """POST /api/v1/config/threshold rejects negative thresholds with 400."""
    client, _ = admin_client
    resp = client.post("/api/v1/config/threshold", json={"threshold": -5})
    assert resp.status_code == 400
    assert "Threshold must be a non-negative integer" in resp.json()["detail"]
