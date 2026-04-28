"""Integration tests for /api/v1/admin/users/*."""

from __future__ import annotations

from fastapi.testclient import TestClient

from insightxpert_api.main import create_app
from insightxpert_api.users import service as users_service
from insightxpert_api.users.models import CreateUserInput


def test_non_admin_forbidden(user_client):
    client, _ = user_client
    assert client.get("/api/v1/admin/users/").status_code == 403
    assert client.post("/api/v1/admin/users/", json={"email": "x@example.com"}).status_code == 403
    assert client.patch("/api/v1/admin/users/abc", json={"role": "user"}).status_code == 403
    assert client.post("/api/v1/admin/users/abc/reset-password").status_code == 403
    assert client.delete("/api/v1/admin/users/abc").status_code == 403


def test_admin_lists_includes_self(admin_client):
    client, admin = admin_client
    r = client.get("/api/v1/admin/users/")
    assert r.status_code == 200
    rows = r.json()
    ids = [row["id"] for row in rows]
    assert admin.id in ids
    me = next(r for r in rows if r["id"] == admin.id)
    assert me["role"] == "admin"
    assert me["is_active"] is True


def test_invite_then_login(admin_client):
    client, _ = admin_client
    r = client.post(
        "/api/v1/admin/users/",
        json={"email": "newbie@example.com", "role": "user"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "newbie@example.com"
    assert body["role"] == "user"
    temp = body["temp_password"]
    assert temp

    # 409 on duplicate
    r2 = client.post("/api/v1/admin/users/", json={"email": "newbie@example.com"})
    assert r2.status_code == 409
    assert r2.json()["detail"] == "email_exists"

    # Fresh client, log in as the invitee
    c2 = TestClient(create_app())
    lr = c2.post(
        "/api/v1/auth/login",
        json={"email": "newbie@example.com", "password": temp},
    )
    assert lr.status_code == 200


def test_patch_role_toggle(admin_client):
    client, _ = admin_client
    # Create a second admin so we don't hit last-admin guard later
    r = client.post("/api/v1/admin/users/", json={"email": "second-admin@example.com", "role": "admin"})
    assert r.status_code == 200
    # Create a plain user
    r2 = client.post("/api/v1/admin/users/", json={"email": "promoteme@example.com", "role": "user"})
    uid = r2.json()["id"]

    # user → admin
    pr = client.patch(f"/api/v1/admin/users/{uid}", json={"role": "admin"})
    assert pr.status_code == 200

    listed = client.get("/api/v1/admin/users/").json()
    row = next(r for r in listed if r["id"] == uid)
    assert row["role"] == "admin"

    # admin → user
    pr2 = client.patch(f"/api/v1/admin/users/{uid}", json={"role": "user"})
    assert pr2.status_code == 200

    # 404 on unknown
    pr3 = client.patch("/api/v1/admin/users/does-not-exist", json={"role": "user"})
    assert pr3.status_code == 404


def test_last_admin_guard_on_demote_and_delete(admin_client):
    client, admin = admin_client

    # Only one admin in the DB (the fixture's). Demoting must 409.
    r = client.patch(f"/api/v1/admin/users/{admin.id}", json={"role": "user"})
    assert r.status_code == 409
    assert r.json()["detail"] == "last_admin"

    # Deleting sole admin must also 409.
    r2 = client.delete(f"/api/v1/admin/users/{admin.id}")
    assert r2.status_code == 409
    assert r2.json()["detail"] == "last_admin"


def test_reset_password_rotates_credential(admin_client):
    client, _ = admin_client
    # Invite, remember the original temp
    r = client.post("/api/v1/admin/users/", json={"email": "rotate@example.com", "role": "user"})
    uid = r.json()["id"]
    original_temp = r.json()["temp_password"]

    # Reset
    rr = client.post(f"/api/v1/admin/users/{uid}/reset-password")
    assert rr.status_code == 200
    new_temp = rr.json()["temp_password"]
    assert new_temp and new_temp != original_temp

    # Old password no longer authenticates; new one does.
    c2 = TestClient(create_app())
    bad = c2.post("/api/v1/auth/login", json={"email": "rotate@example.com", "password": original_temp})
    assert bad.status_code == 401

    c3 = TestClient(create_app())
    good = c3.post("/api/v1/auth/login", json={"email": "rotate@example.com", "password": new_temp})
    assert good.status_code == 200

    # 404 on unknown
    bad_reset = client.post("/api/v1/admin/users/does-not-exist/reset-password")
    assert bad_reset.status_code == 404


def test_delete_user(admin_client):
    client, _ = admin_client
    r = client.post("/api/v1/admin/users/", json={"email": "delete-me@example.com", "role": "user"})
    uid = r.json()["id"]
    dr = client.delete(f"/api/v1/admin/users/{uid}")
    assert dr.status_code == 200
    # Gone from list
    assert uid not in [row["id"] for row in client.get("/api/v1/admin/users/").json()]
    # Second delete → 404
    dr2 = client.delete(f"/api/v1/admin/users/{uid}")
    assert dr2.status_code == 404


def test_admin_can_disable_sharing(admin_client):
    client, _ = admin_client
    r = client.post("/api/v1/admin/users/", json={"email": "share-target@example.com", "role": "user"})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]

    resp = client.patch(
        f"/api/v1/admin/users/{uid}/sharing-disabled",
        json={"disabled": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sharing_disabled"] is True

    resp = client.patch(
        f"/api/v1/admin/users/{uid}/sharing-disabled",
        json={"disabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["sharing_disabled"] is False

    # 404 on unknown user
    resp404 = client.patch(
        "/api/v1/admin/users/does-not-exist/sharing-disabled",
        json={"disabled": True},
    )
    assert resp404.status_code == 404


def test_non_admin_cannot_toggle_sharing(user_client):
    user_c, user = user_client
    resp = user_c.patch(
        f"/api/v1/admin/users/{user.id}/sharing-disabled",
        json={"disabled": True},
    )
    assert resp.status_code in (401, 403)
