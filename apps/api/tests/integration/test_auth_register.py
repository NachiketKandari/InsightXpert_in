from __future__ import annotations

from fastapi.testclient import TestClient

from insightxpert_api.config import get_settings
from insightxpert_api.main import create_app
from insightxpert_api.users import repository, service
from insightxpert_api.users.models import CreateUserInput


def test_register_returns_201_and_sets_cookie(fresh_db):
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "fresh@example.com", "password": "securepassword"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "fresh@example.com"
    assert body["role"] == "user"
    assert body["must_change_password"] is False
    cookie_name = get_settings().session_cookie_name
    assert cookie_name in resp.cookies


def test_register_duplicate_email_returns_409(fresh_db):
    service.register("dup@example.com", "securepassword")
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "anotherpassword"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "email_exists"


def test_register_short_password_returns_422(fresh_db):
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "ok@example.com", "password": "short"},
    )
    assert resp.status_code == 422


def test_register_disabled_returns_403(fresh_db, monkeypatch):
    monkeypatch.setenv("REGISTRATION_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "nope@example.com", "password": "securepassword"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "registration is disabled"
    finally:
        get_settings.cache_clear()


def test_register_auto_login_via_me(fresh_db):
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "autologin@example.com", "password": "securepassword"},
    )
    assert resp.status_code == 201
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "autologin@example.com"


def test_register_disabled_login_still_works(fresh_db, monkeypatch):
    """Login and admin invite must still work when registration is off."""
    invited = service.invite(CreateUserInput(email="existing@example.com"))
    monkeypatch.setenv("REGISTRATION_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "existing@example.com", "password": invited.temp_password},
        )
        assert resp.status_code == 200
    finally:
        get_settings.cache_clear()
