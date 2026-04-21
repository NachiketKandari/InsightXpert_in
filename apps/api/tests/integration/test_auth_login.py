from __future__ import annotations

from fastapi.testclient import TestClient

from insightxpert_api.main import create_app
from insightxpert_api.users import service
from insightxpert_api.users.models import CreateUserInput


def test_login_wrong_password_returns_401(fresh_db):
    service.invite(CreateUserInput(email="a@example.com"))
    client = TestClient(create_app())
    resp = client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(fresh_db):
    client = TestClient(create_app())
    resp = client.post("/api/v1/auth/login", json={"email": "n@o.com", "password": "whatever"})
    assert resp.status_code == 401


def test_login_correct_password_sets_cookie_and_returns_user(fresh_db):
    invited = service.invite(CreateUserInput(email="a@example.com"))
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "a@example.com"
    assert body["role"] == "user"
    assert body["must_change_password"] is True
    from insightxpert_api.config import get_settings
    assert get_settings().session_cookie_name in resp.cookies


def test_login_inactive_user_returns_401(fresh_db):
    invited = service.invite(CreateUserInput(email="a@example.com"))
    from insightxpert_api.users import repository
    repository.update_user(invited.user.id, {"is_active": 0})
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 401


def test_unlock_returns_410(fresh_db):
    client = TestClient(create_app())
    resp = client.post("/api/v1/auth/unlock", json={"password": "dev"})
    assert resp.status_code == 410
