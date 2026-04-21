"""Integration tests for /api/v1/admin/databases — enriched admin DB list.

The user-facing ``GET /api/v1/databases`` endpoint is covered by
``test_databases_visibility.py``; this file only asserts the admin-enriched
shape (owner_email + shared_with).
"""

from __future__ import annotations

from insightxpert_api.users import service as users_service
from insightxpert_api.users.models import CreateUserInput


def test_non_admin_forbidden(user_client):
    client, _ = user_client
    r = client.get("/api/v1/admin/databases/")
    assert r.status_code == 403


def test_admin_list_shows_bundled_as_public(admin_client):
    client, _ = admin_client
    r = client.get("/api/v1/admin/databases/")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 6
    by_id = {row["db_id"] for row in rows}
    assert "california_schools" in by_id
    assert "formula_1" in by_id
    for row in rows:
        assert row["visibility"] == "public"
        assert row["owner_user_id"] is None
        assert row["owner_email"] is None
        assert row["shared_with"] == []
        assert isinstance(row["size_bytes"], int)
        assert isinstance(row["created_at"], int)


def test_admin_list_reflects_share_list(admin_client):
    client, admin = admin_client
    # Invite a second user to receive a share.
    invited = users_service.invite(
        CreateUserInput(email="sharee@example.com", role="user")
    )
    other_id = invited.user.id

    # Flip california_schools to shared with that user.
    set_r = client.post(
        "/api/v1/databases/california_schools/visibility",
        json={"visibility": "shared", "shared_with": [other_id]},
    )
    assert set_r.status_code == 200

    r = client.get("/api/v1/admin/databases/")
    assert r.status_code == 200
    rows = r.json()
    ca = next(row for row in rows if row["db_id"] == "california_schools")
    assert ca["visibility"] == "shared"
    shared = ca["shared_with"]
    assert len(shared) == 1
    assert shared[0]["user_id"] == other_id
    assert shared[0]["email"] == "sharee@example.com"

    # Untouched DBs are unaffected.
    formula = next(row for row in rows if row["db_id"] == "formula_1")
    assert formula["visibility"] == "public"
    assert formula["shared_with"] == []


def test_admin_list_owner_email_for_uploaded_db(admin_client, fresh_db):
    """An uploaded DB's admin row shows the uploader's email."""
    from insightxpert_api.databases import service as vis_service

    # Simulate upload registration: the upload route calls upsert_private.
    vis_service.upsert_private("user_uploaded_db", admin_client[1].id, 1234)

    client, admin = admin_client
    r = client.get("/api/v1/admin/databases/")
    assert r.status_code == 200
    rows = r.json()
    row = next(row for row in rows if row["db_id"] == "user_uploaded_db")
    assert row["owner_user_id"] == admin.id
    assert row["owner_email"] == "admin@example.com"
    assert row["visibility"] == "private"
    assert row["size_bytes"] == 1234
    assert row["shared_with"] == []
