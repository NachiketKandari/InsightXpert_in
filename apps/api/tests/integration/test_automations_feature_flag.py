"""Feature-flag tests: when AUTOMATIONS_ENABLED=false, user routes 404.

Internal endpoint always mounted; returns 503 when flag off (covered in
test_automations_internal_endpoint.test_internal_endpoint_returns_503_when_flag_off)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from insightxpert_api.main import create_app


def test_automations_route_404_when_flag_off(monkeypatch, fresh_db):
    from insightxpert_api.config import get_settings
    monkeypatch.setenv("AUTOMATIONS_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    r = client.get("/api/v1/automations")
    # Without auth we might get 401, but route itself shouldn't be mounted → 404
    assert r.status_code == 404


def test_notifications_route_404_when_flag_off(monkeypatch, fresh_db):
    from insightxpert_api.config import get_settings
    monkeypatch.setenv("AUTOMATIONS_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    r = client.get("/api/v1/notifications")
    assert r.status_code == 404


def test_trigger_templates_route_404_when_flag_off(monkeypatch, fresh_db):
    from insightxpert_api.config import get_settings
    monkeypatch.setenv("AUTOMATIONS_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    r = client.get("/api/v1/automations/templates")
    assert r.status_code == 404


def test_automations_route_mounted_when_flag_on(user_client_automations):
    client, _ = user_client_automations
    # Authed request returns an empty list, not 404.
    r = client.get("/api/v1/automations")
    assert r.status_code == 200
    assert r.json() == []
