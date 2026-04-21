"""Integration tests for DB visibility filtering + admin visibility endpoint."""

from __future__ import annotations

from insightxpert_api.databases import service as vis_service


def test_non_admin_sees_public(user_client):
    client, _ = user_client
    r = client.get("/api/v1/databases")
    assert r.status_code == 200
    ids = {row["db_id"] for row in r.json()}
    # Bundled DBs seeded as public in migration — all visible.
    assert "california_schools" in ids


def test_non_admin_does_not_see_private_bundled(user_client):
    """If admin flips a bundled DB private, non-admin no longer sees it."""
    client, _ = user_client
    # Flip 'formula_1' to private via the service directly (admin route is tested elsewhere)
    vis_service.set_visibility("formula_1", "private", None)
    r = client.get("/api/v1/databases")
    ids = {row["db_id"] for row in r.json()}
    assert "formula_1" not in ids
    # Other bundled DBs still visible
    assert "california_schools" in ids


def test_admin_sees_private_databases(admin_client):
    """Admin bypasses visibility filter."""
    client, _ = admin_client
    vis_service.set_visibility("formula_1", "private", None)
    r = client.get("/api/v1/databases")
    assert r.status_code == 200
    ids = {row["db_id"] for row in r.json()}
    # Even though formula_1 is private, admin sees it.
    assert "formula_1" in ids
    assert "california_schools" in ids


def test_admin_can_flip_public_to_private(admin_client):
    client, _ = admin_client

    # california_schools starts public per migration seed; hide it.
    r = client.post(
        "/api/v1/databases/california_schools/visibility",
        json={"visibility": "private"},
    )
    assert r.status_code == 200

    # Admin still sees it
    admin_list = client.get("/api/v1/databases").json()
    assert "california_schools" in {row["db_id"] for row in admin_list}

    # A fresh non-admin should not
    from fastapi.testclient import TestClient
    from insightxpert_api.main import create_app
    from insightxpert_api.users import service as users_service
    from insightxpert_api.users.models import CreateUserInput

    invited = users_service.invite(CreateUserInput(email="viewer@example.com", role="user"))
    c2 = TestClient(create_app())
    assert c2.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.com", "password": invited.temp_password},
    ).status_code == 200
    viewer_list = c2.get("/api/v1/databases").json()
    # But uploaded-only listings still include filesystem entries they've uploaded —
    # for california_schools (bundled) that's not applicable, so it must be gone.
    # (Bundled files without a visible row are filtered out.)
    assert "california_schools" not in {row["db_id"] for row in viewer_list}


def test_admin_can_share_private_db_with_user(admin_client):
    client, _ = admin_client
    # Set up a private DB + a user to share with
    vis_service.create("secret_db", owner_user_id="ownerX", visibility="private")

    from insightxpert_api.users import service as users_service
    from insightxpert_api.users.models import CreateUserInput

    invited = users_service.invite(CreateUserInput(email="shareto@example.com", role="user"))

    # Share
    r = client.post(
        "/api/v1/databases/secret_db/visibility",
        json={"visibility": "shared", "shared_with": [invited.user.id]},
    )
    assert r.status_code == 200

    # The shared user now sees it in the visibility table's listing.
    ids = vis_service.visible_ids(invited.user.id, is_admin=False)
    assert "secret_db" in ids

    # A third party does not
    others = vis_service.visible_ids("random-user", is_admin=False)
    assert "secret_db" not in others


def test_non_admin_cannot_change_visibility(user_client):
    client, _ = user_client
    r = client.post(
        "/api/v1/databases/california_schools/visibility",
        json={"visibility": "private"},
    )
    assert r.status_code == 403


def test_upload_registers_db_as_private(user_client):
    client, user = user_client
    import io
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.executescript("CREATE TABLE t (x INT); INSERT INTO t VALUES (1);")
    con.commit()
    data = bytes(con.serialize())
    con.close()

    r = client.post(
        "/api/v1/databases/upload",
        data={"db_id": "vis_upload"},
        files={"file": ("u.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text

    # Row exists, private, owner is the uploader
    from insightxpert_api.databases import repository as vis_repo

    row = vis_repo.get("vis_upload")
    assert row is not None
    assert row["visibility"] == "private"
    assert row["owner_user_id"] == user.id
    assert row["size_bytes"] > 0
