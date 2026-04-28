"""Gating tests for share-snapshot creation."""
from __future__ import annotations

import time

import pytest

from insightxpert_api.shared_snapshots.service import (
    PostgresShareRefused,
    SharingDisabled,
    UploadedShareRequiresConsent,
    create_snapshot,
)


def _seed_conversation(user_id: str, db_id: str | None) -> str:
    """Insert a minimal conversation + 1 message; return conversation_id."""
    import uuid

    from sqlalchemy import insert as sa_insert

    from insightxpert_api.db.engine import get_engine
    from insightxpert_api.orchestration.table import conversations, messages

    cid = str(uuid.uuid4())
    now = int(time.time())
    with get_engine().begin() as conn:
        conn.execute(
            sa_insert(conversations).values(
                id=cid,
                user_id=user_id,
                db_id=db_id,
                title="Test",
                is_starred=0,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            sa_insert(messages).values(
                id=str(uuid.uuid4()),
                conversation_id=cid,
                role="user",
                content="hello",
                chunks_json=None,
                tokens_in=None,
                tokens_out=None,
                created_at=now,
            )
        )
    return cid


def _seed_user(user_id: str, *, sharing_disabled: bool = False) -> None:
    import time as _t

    from sqlalchemy import insert as sa_insert

    from insightxpert_api.users.table import users
    from insightxpert_api.db.engine import get_engine

    now = int(_t.time())
    with get_engine().begin() as conn:
        conn.execute(
            sa_insert(users).values(
                id=user_id,
                email=f"{user_id}@test.local",
                password_hash="x",
                role="user",
                is_active=1,
                must_change_password=0,
                sessions_valid_after=now,
                sharing_disabled=1 if sharing_disabled else 0,
                created_at=now,
                updated_at=now,
            )
        )


def _seed_uploaded_db(user_id: str, db_id: str) -> None:
    from insightxpert_api.databases import repository as db_repo

    db_repo.upsert_private(
        db_id=db_id,
        owner_user_id=user_id,
        size_bytes=0,
        kind="sqlite_file",
    )


def _seed_postgres_db(user_id: str, db_id: str) -> None:
    from insightxpert_api.databases import repository as db_repo

    db_repo.upsert_private(
        db_id=db_id,
        owner_user_id=user_id,
        size_bytes=0,
        kind="postgres",
    )


def test_bundled_db_no_consent_required(fresh_db):
    user = "u-bundled-" + str(int(time.time() * 1000))
    _seed_user(user)
    cid = _seed_conversation(user, db_id="california_schools")  # bundled, no row in databases
    meta = create_snapshot(
        conversation_id=cid,
        user_id=user,
        acknowledge_uploaded=False,
    )
    assert meta.token
    assert meta.expires_at and meta.expires_at > meta.created_at


def test_uploaded_sqlite_refuses_without_consent(fresh_db):
    user = "u-up-" + str(int(time.time() * 1000))
    _seed_user(user)
    _seed_uploaded_db(user, "my_upload.db")
    cid = _seed_conversation(user, db_id="my_upload.db")
    with pytest.raises(UploadedShareRequiresConsent):
        create_snapshot(
            conversation_id=cid,
            user_id=user,
            acknowledge_uploaded=False,
        )


def test_uploaded_sqlite_succeeds_with_consent(fresh_db):
    user = "u-up2-" + str(int(time.time() * 1000))
    _seed_user(user)
    _seed_uploaded_db(user, "my_upload2.db")
    cid = _seed_conversation(user, db_id="my_upload2.db")
    meta = create_snapshot(
        conversation_id=cid,
        user_id=user,
        acknowledge_uploaded=True,
    )
    assert meta.token


def test_postgres_always_refused(fresh_db):
    user = "u-pg-" + str(int(time.time() * 1000))
    _seed_user(user)
    _seed_postgres_db(user, "pg_demo")
    cid = _seed_conversation(user, db_id="pg_demo")
    with pytest.raises(PostgresShareRefused):
        create_snapshot(
            conversation_id=cid,
            user_id=user,
            acknowledge_uploaded=True,
        )


def test_user_with_sharing_disabled_refused(fresh_db):
    user = "u-dis-" + str(int(time.time() * 1000))
    _seed_user(user, sharing_disabled=True)
    cid = _seed_conversation(user, db_id=None)
    with pytest.raises(SharingDisabled):
        create_snapshot(
            conversation_id=cid,
            user_id=user,
            acknowledge_uploaded=False,
        )
