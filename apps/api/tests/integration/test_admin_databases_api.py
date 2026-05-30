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
    by_id = {row["db_id"] for row in rows}
    # Seeded DBs always present. Bundled DBs (california_schools, formula_1,
    # etc.) only present when fetch-bundled-dbs.sh has been run.
    assert "transactions" in by_id
    assert "toxicology_pg" in by_id
    assert len(rows) >= 2
    for row in rows:
        assert row["visibility"] == "public"
        assert row["owner_user_id"] is None
        assert row["owner_email"] is None
        assert row["shared_with"] == []
        # Seeded DBs (transactions, toxicology_pg) have no local file;
        # bundled DBs loaded from disk will report a concrete size.
        if row["db_id"] == "toxicology_pg":
            assert row["size_bytes"] is None
        elif row["db_id"] == "transactions":
            assert row["size_bytes"] is None or isinstance(row["size_bytes"], int)
        else:
            assert isinstance(row["size_bytes"], int)
        assert isinstance(row["created_at"], int)


def test_admin_list_reflects_share_list(admin_client):
    client, admin = admin_client
    # Invite a second user to receive a share.
    invited = users_service.invite(
        CreateUserInput(email="sharee@example.com", role="user")
    )
    other_id = invited.user.id

    # Use a seeded DB (always present) instead of a bundled one.
    set_r = client.post(
        "/api/v1/databases/transactions/visibility",
        json={"visibility": "shared", "shared_with": [other_id]},
    )
    assert set_r.status_code == 200

    r = client.get("/api/v1/admin/databases/")
    assert r.status_code == 200
    rows = r.json()
    tx = next(row for row in rows if row["db_id"] == "transactions")
    assert tx["visibility"] == "shared"
    shared = tx["shared_with"]
    assert len(shared) == 1
    assert shared[0]["user_id"] == other_id
    assert shared[0]["email"] == "sharee@example.com"

    # Untouched DBs are unaffected.
    tox = next(row for row in rows if row["db_id"] == "toxicology_pg")
    assert tox["visibility"] == "public"
    assert tox["shared_with"] == []


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
