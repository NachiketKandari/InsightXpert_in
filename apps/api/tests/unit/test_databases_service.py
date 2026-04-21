"""Unit tests for databases.service (visibility filter + sharing)."""

from __future__ import annotations

import pytest

from insightxpert_api.databases import repository, service


def _seed(db_id: str, owner: str | None, visibility: str) -> None:
    service.create(db_id, owner_user_id=owner, visibility=visibility, size_bytes=0)


def test_list_visible_public_only_for_other_users(fresh_db):
    _seed("public_one", owner=None, visibility="public")
    _seed("alice_private", owner="alice", visibility="private")
    visible = service.list_visible(user_id="bob", is_admin=False)
    ids = {r["db_id"] for r in visible}
    # Bundled DBs from migration are also public
    assert "public_one" in ids
    assert "alice_private" not in ids


def test_list_visible_includes_own(fresh_db):
    _seed("alice_private", owner="alice", visibility="private")
    ids = {r["db_id"] for r in service.list_visible("alice", is_admin=False)}
    assert "alice_private" in ids


def test_list_visible_includes_shared(fresh_db):
    _seed("team_db", owner="alice", visibility="shared")
    service.set_visibility("team_db", "shared", shared_with=["bob"])
    bob_ids = {r["db_id"] for r in service.list_visible("bob", is_admin=False)}
    carol_ids = {r["db_id"] for r in service.list_visible("carol", is_admin=False)}
    assert "team_db" in bob_ids
    assert "team_db" not in carol_ids


def test_admin_sees_all(fresh_db):
    _seed("alice_private", owner="alice", visibility="private")
    _seed("bob_private", owner="bob", visibility="private")
    admin_ids = {r["db_id"] for r in service.list_visible("anyone", is_admin=True)}
    assert {"alice_private", "bob_private"} <= admin_ids


def test_set_visibility_wipes_old_shares(fresh_db):
    _seed("shared_db", owner="alice", visibility="shared")
    service.set_visibility("shared_db", "shared", shared_with=["bob", "carol"])
    # Switch to private — shares must go.
    service.set_visibility("shared_db", "private", shared_with=None)
    bob_ids = {r["db_id"] for r in service.list_visible("bob", is_admin=False)}
    assert "shared_db" not in bob_ids


def test_invalid_visibility_rejected(fresh_db):
    with pytest.raises(service.InvalidVisibilityError):
        service.set_visibility("whatever", "chaos", None)


def test_upsert_private_idempotent(fresh_db):
    service.upsert_private("my_upload", owner_user_id="alice", size_bytes=100)
    service.upsert_private("my_upload", owner_user_id="alice", size_bytes=200)
    row = repository.get("my_upload")
    assert row is not None
    assert row["size_bytes"] == 200
    assert row["visibility"] == "private"
