"""Public viewer route tests — GET /api/v1/public/shares/{token} (no auth)."""
from __future__ import annotations

import time
import uuid

import pytest

from fastapi.testclient import TestClient

from insightxpert_api.main import app
from insightxpert_api.shared_snapshots import repository as snap_repo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_conversation_for_user(user_id: str) -> str:
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
                db_id=None,
                title="Public Test Convo",
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
                content="hello from public test",
                chunks_json=None,
                tokens_in=None,
                tokens_out=None,
                created_at=now,
            )
        )
    return cid


# anon client — no cookies set, simulates unauthenticated viewer
anon = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unauth_get_existing_returns_payload(fresh_db, user_client):
    client, user = user_client
    cid = _seed_conversation_for_user(user.id)

    # Create share via authenticated route
    resp = client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": False},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    # Fetch via public route (no auth)
    pub = anon.get(f"/api/v1/public/shares/{token}")
    assert pub.status_code == 200, pub.text
    body = pub.json()

    # Must have viewable fields
    assert "messages" in body
    assert "title" in body

    # Must NOT expose private identifiers
    assert "conversation_id" not in body
    assert "owner_user_id" not in body
    assert "db_id" not in body


def test_unauth_get_revoked_returns_404(fresh_db, user_client):
    client, user = user_client
    cid = _seed_conversation_for_user(user.id)

    resp = client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": False},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    # Revoke via authenticated DELETE
    del_resp = client.delete(f"/api/v1/conversations/{cid}/share")
    assert del_resp.status_code == 204

    # Public GET must 404
    pub = anon.get(f"/api/v1/public/shares/{token}")
    assert pub.status_code == 404


def test_unauth_get_expired_returns_404(fresh_db):
    token = "tok_expired_" + str(int(time.time() * 1000))
    now = int(time.time())
    snap_repo.insert(
        token=token,
        conversation_id="c-expired",
        owner_user_id="u-expired",
        db_id=None,
        db_kind="sqlite_file",
        title="Expired",
        payload_json='{"title":"Expired","dataset_name":null,"messages":[]}',
        created_at=now - 100,
        expires_at=now - 1,  # already expired
    )

    pub = anon.get(f"/api/v1/public/shares/{token}")
    assert pub.status_code == 404


def test_view_increments_counter(fresh_db, user_client):
    client, user = user_client
    cid = _seed_conversation_for_user(user.id)

    resp = client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": False},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    # Hit public route twice
    r1 = anon.get(f"/api/v1/public/shares/{token}")
    assert r1.status_code == 200
    r2 = anon.get(f"/api/v1/public/shares/{token}")
    assert r2.status_code == 200

    # Check view_count via owner route
    meta = client.get(f"/api/v1/conversations/{cid}/share")
    assert meta.status_code == 200, meta.text
    assert meta.json()["view_count"] == 2


def test_response_has_noindex_header(fresh_db, user_client):
    client, user = user_client
    cid = _seed_conversation_for_user(user.id)

    resp = client.post(
        f"/api/v1/conversations/{cid}/share",
        json={"acknowledge_uploaded": False},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    pub = anon.get(f"/api/v1/public/shares/{token}")
    assert pub.status_code == 200
    robots = pub.headers.get("x-robots-tag", "")
    assert "noindex" in robots
