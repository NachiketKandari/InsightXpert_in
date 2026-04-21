"""End-to-end lifecycle: invite → login → forced change-password → authenticated call → logout."""

from __future__ import annotations

from fastapi.testclient import TestClient

from insightxpert_api.main import create_app
from insightxpert_api.users import service
from insightxpert_api.users.models import CreateUserInput


def test_full_auth_lifecycle(fresh_db):
    invited = service.invite(CreateUserInput(email="eve@example.com"))

    client = TestClient(create_app())

    # 1. login with temp password works
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "eve@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is True

    # 2. /me reflects state
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "eve@example.com"
    assert resp.json()["must_change_password"] is True

    # 3. change password; must succeed
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": invited.temp_password, "new_password": "a-new-strong-pw-99"},
    )
    assert resp.status_code == 200

    # 4. Note: change_password bumps sessions_valid_after, so the current cookie is
    # now invalidated. The user must log in again. Verify /me is 401 before re-login.
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401

    # 5. old temp password no longer works at login
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "eve@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 401

    # 6. new password works at login
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "eve@example.com", "password": "a-new-strong-pw-99"},
    )
    assert resp.status_code == 200

    # 7. /me now shows must_change_password = false
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is False

    # 8. logout clears cookie
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200

    # 9. /me returns 401 after logout
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
