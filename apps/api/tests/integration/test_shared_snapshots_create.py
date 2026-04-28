"""Repository-level tests and HTTP route tests for shared_snapshots."""
from __future__ import annotations

import time
import uuid

import pytest

from insightxpert_api.shared_snapshots import repository as repo


def test_insert_then_get_roundtrip(fresh_db):
    token = "tok_test_roundtrip_" + str(int(time.time() * 1000))
    repo.insert(
        token=token,
        conversation_id="c-roundtrip",
        owner_user_id="u-roundtrip",
        db_id="bundled_demo",
        db_kind="sqlite_file",
        title="Demo",
        payload_json='{"messages":[]}',
        created_at=1700000000,
        expires_at=1700000000 + 90 * 86400,
    )

    row = repo.get_by_token(token)
    assert row is not None
    assert row["conversation_id"] == "c-roundtrip"
    assert row["owner_user_id"] == "u-roundtrip"
    assert row["payload_json"] == '{"messages":[]}'
    assert row["revoked_at"] is None


def test_revoke_sets_timestamp(fresh_db):
    token = "tok_test_revoke_" + str(int(time.time() * 1000))
    repo.insert(
        token=token,
        conversation_id="c-rev",
        owner_user_id="u-rev",
        db_id=None,
        db_kind="sqlite_file",
        title=None,
        payload_json='{}',
        created_at=1700000000,
        expires_at=None,
    )
    repo.revoke(token)
    row = repo.get_by_token(token)
    assert row is not None
    assert row["revoked_at"] is not None and row["revoked_at"] > 0


# ---------------------------------------------------------------------------
# HTTP route tests (auth-required: POST / GET / DELETE /conversations/{id}/share)
# ---------------------------------------------------------------------------


def _seed_conversation_for_user(user_id: str, db_id: str | None = None) -> str:
    """Insert a minimal conversation + 1 message owned by ``user_id``."""
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
                title="Route Test Convo",
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
                content="hello from route test",
                chunks_json=None,
                tokens_in=None,
                tokens_out=None,
                created_at=now,
            )
        )
    return cid


def _seed_postgres_db_for_user(user_id: str, db_id: str) -> None:
    from insightxpert_api.databases import repository as db_repo

    db_repo.upsert_private(
        db_id=db_id,
        owner_user_id=user_id,
        size_bytes=0,
        kind="postgres",
    )


def test_post_share_returns_meta(user_client):
    client, user = user_client
    cid = _seed_conversation_for_user(user.id)
    resp = client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"]
    assert body["share_url"].startswith("/share/")
    assert body["revoked"] is False
    assert body["view_count"] == 0


def test_post_share_postgres_refused(user_client):
    client, user = user_client
    pg_db_id = "pg_route_" + str(int(time.time() * 1000))
    _seed_postgres_db_for_user(user.id, pg_db_id)
    cid = _seed_conversation_for_user(user.id, db_id=pg_db_id)
    resp = client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": True},
    )
    assert resp.status_code == 403
    assert "postgres" in resp.text.lower() or "refused" in resp.text.lower()


def test_delete_share_revokes(user_client):
    client, user = user_client
    cid = _seed_conversation_for_user(user.id)
    client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": False},
    ).raise_for_status()
    resp = client.delete(f"/api/v1/conversations/{cid}/share")
    assert resp.status_code == 204
    follow = client.get(f"/api/v1/conversations/{cid}/share")
    assert follow.status_code == 404
