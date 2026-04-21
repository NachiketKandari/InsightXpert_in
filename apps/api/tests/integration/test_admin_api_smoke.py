"""B3 admin API smoke tests.

Exercises every new admin endpoint shipped in B3, asserting status codes and
response shapes. Uses the ``admin_client`` fixture (pre-authenticated admin)
from conftest.py, plus ``user_client`` to verify 403 enforcement.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/users/"),
    ("GET", "/api/v1/admin/overview"),
    ("GET", "/api/v1/admin/audit?limit=5"),
    ("GET", "/api/v1/admin/metrics?limit=5"),
    ("GET", "/api/v1/admin/conversations/?limit=5"),
    ("GET", "/api/v1/admin/prompts/"),
    ("GET", "/api/v1/admin/databases/"),
]


# ---------------------------------------------------------------------------
# Admin happy-path tests
# ---------------------------------------------------------------------------


def test_admin_users_list(admin_client):
    """GET /api/v1/admin/users/ returns 200 and a list that contains the admin."""
    client, admin_user = admin_client
    resp = client.get("/api/v1/admin/users/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    emails = [u["email"] for u in data]
    assert admin_user.email in emails


def test_admin_overview_shape(admin_client):
    """GET /api/v1/admin/overview returns 200 with all required KPI keys."""
    client, _ = admin_client
    resp = client.get("/api/v1/admin/overview")
    assert resp.status_code == 200
    data = resp.json()
    required = {
        "active_users_24h",
        "total_users",
        "chats_today",
        "tokens_today",
        "thumbs_ratio_7d",
        "sparkline_7d",
    }
    assert required <= data.keys()
    assert isinstance(data["sparkline_7d"], list)


def test_admin_audit_shape(admin_client):
    """GET /api/v1/admin/audit?limit=5 returns 200 with {rows, next_cursor}."""
    client, _ = admin_client
    resp = client.get("/api/v1/admin/audit?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert "next_cursor" in data
    assert isinstance(data["rows"], list)


def test_admin_metrics_shape(admin_client):
    """GET /api/v1/admin/metrics?limit=5 returns 200 with {rows, next_cursor}."""
    client, _ = admin_client
    resp = client.get("/api/v1/admin/metrics?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert "next_cursor" in data
    assert isinstance(data["rows"], list)


def test_admin_conversations_shape(admin_client):
    """GET /api/v1/admin/conversations/?limit=5 returns 200 with {rows, next_cursor}."""
    client, _ = admin_client
    resp = client.get("/api/v1/admin/conversations/?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert "next_cursor" in data
    assert isinstance(data["rows"], list)


def test_admin_prompts_source_field(admin_client):
    """GET /api/v1/admin/prompts/ returns 200 and each item has a `source` field."""
    client, _ = admin_client
    resp = client.get("/api/v1/admin/prompts/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert "source" in item, f"Missing 'source' on prompt item: {item}"
        assert item["source"] in ("db", "file")


def test_admin_databases_shared_with_field(admin_client):
    """GET /api/v1/admin/databases/ returns 200 and each item has a `shared_with` field."""
    client, _ = admin_client
    resp = client.get("/api/v1/admin/databases/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for item in data:
        assert "shared_with" in item, f"Missing 'shared_with' on database item: {item}"


# ---------------------------------------------------------------------------
# Non-admin 403 enforcement — parametrized, one case per endpoint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_non_admin(user_client, method, path):
    """Every admin endpoint must return 403 for a regular user."""
    client, _ = user_client
    caller = getattr(client, method.lower())
    resp = caller(path)
    assert resp.status_code == 403, (
        f"{method} {path} should return 403 for non-admin; got {resp.status_code}"
    )
