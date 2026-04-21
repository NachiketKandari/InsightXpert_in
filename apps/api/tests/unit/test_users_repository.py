from __future__ import annotations

import time

import pytest
import sqlalchemy.exc

from insightxpert_api.users.models import UserWithHash
from insightxpert_api.users.repository import (
    count_active_admins,
    delete_user,
    get_by_email,
    get_by_id,
    insert_user,
    list_users,
    update_user,
)


def _fixture_user(
    email: str = "a@example.com",
    role: str = "user",
    uid: str = "00000000-0000-0000-0000-000000000001",
) -> UserWithHash:
    now = int(time.time())
    return UserWithHash(
        id=uid,
        email=email,
        role=role,
        is_active=True,
        must_change_password=False,
        sessions_valid_after=now,
        created_at=now,
        updated_at=now,
        last_seen_at=None,
        password_hash="not-a-real-hash",
    )


def test_insert_then_get_by_id_returns_user(fresh_db):
    u = _fixture_user()
    insert_user(u)
    got = get_by_id(u.id)
    assert got is not None
    assert got.email == "a@example.com"
    assert got.password_hash == "not-a-real-hash"


def test_get_by_id_missing_returns_none(fresh_db):
    assert get_by_id("nope") is None


def test_get_by_email_is_case_insensitive(fresh_db):
    insert_user(_fixture_user(email="Mixed@Example.COM"))
    assert get_by_email("mixed@example.com") is not None


def test_insert_duplicate_email_raises(fresh_db):
    insert_user(_fixture_user())
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        insert_user(_fixture_user())


def test_update_user_changes_fields(fresh_db):
    u = _fixture_user()
    insert_user(u)
    update_user(u.id, {"role": "admin", "updated_at": u.updated_at + 1})
    got = get_by_id(u.id)
    assert got is not None and got.role == "admin"


def test_delete_user_removes_row(fresh_db):
    u = _fixture_user()
    insert_user(u)
    delete_user(u.id)
    assert get_by_id(u.id) is None


def test_list_users_returns_all(fresh_db):
    insert_user(_fixture_user(email="a@x.com"))
    insert_user(_fixture_user(email="b@x.com", uid="00000000-0000-0000-0000-000000000002"))
    xs = list_users()
    assert len(xs) == 2


def test_count_active_admins_matches(fresh_db):
    insert_user(_fixture_user(email="u@x.com", role="user"))
    insert_user(_fixture_user(email="a@x.com", role="admin", uid="00000000-0000-0000-0000-000000000002"))
    assert count_active_admins() == 1
