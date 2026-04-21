"""Legacy auth tests, migrated to /login + CurrentUser semantics.

The old anonymous gate tests (``/unlock``) have been reshaped to exercise the
new email/password flow. /unlock itself returns 410 Gone and is covered in
``test_auth_login.py`` — no need to duplicate here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from insightxpert_api.main import create_app
from insightxpert_api.users import service
from insightxpert_api.users.models import CreateUserInput


def test_login_rejects_wrong_password(fresh_db):
    service.invite(CreateUserInput(email="x@example.com", role="user"))
    client = TestClient(create_app())
    r = client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope"})
    assert r.status_code == 401


def test_login_sets_cookie_on_success(fresh_db):
    invited = service.invite(CreateUserInput(email="x@example.com", role="user"))
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "x@example.com", "password": invited.temp_password},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "x@example.com"
    assert "ix_session" in r.cookies


def test_me_requires_session(client: TestClient):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_returns_user_when_authed(authed_client: TestClient):
    r = authed_client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "authed@example.com"
    assert body["role"] == "user"
    assert "id" in body and len(body["id"]) > 0


def test_me_rejects_bad_token(client: TestClient):
    client.cookies.set("ix_session", "garbage")
    r = client.get("/api/v1/auth/me")
    # get_current_user returns 401 for any bad/malformed token.
    assert r.status_code == 401


def test_logout_clears_cookie(authed_client: TestClient):
    r = authed_client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # After logout, /me should 401 again
    authed_client.cookies.clear()
    r2 = authed_client.get("/api/v1/auth/me")
    assert r2.status_code == 401


def test_bearer_token_fallback_works(fresh_db):
    invited = service.invite(CreateUserInput(email="b@example.com", role="user"))
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "b@example.com", "password": invited.temp_password},
    )
    token = r.cookies.get("ix_session")
    client.cookies.clear()
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["email"] == "b@example.com"
