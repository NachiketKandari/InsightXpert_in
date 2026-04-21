"""Integration tests for /api/v1/admin/conversations/*.

Covers:
- RBAC (non-admin → 403)
- empty list
- chat-turn snapshot lands in conversations + messages tables
- admin list JOINs user_email
- detail returns parsed chunks_json
- user_id filter
- cursor pagination across 25 rows
- delete cascades to messages
"""

from __future__ import annotations

import json
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from insightxpert_api.main import create_app
from insightxpert_api.users import service as users_service
from insightxpert_api.users.models import CreateUserInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_and_user_clients(fresh_db):
    """Invite an admin AND a regular user, log in both. Returns (admin_client, admin, user_client, user)."""
    admin_invited = users_service.invite(
        CreateUserInput(email="admin@example.com", role="admin")
    )
    user_invited = users_service.invite(
        CreateUserInput(email="user@example.com", role="user")
    )

    admin_c = TestClient(create_app())
    ar = admin_c.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": admin_invited.temp_password},
    )
    assert ar.status_code == 200

    user_c = TestClient(create_app())
    ur = user_c.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": user_invited.temp_password},
    )
    assert ur.status_code == 200

    return admin_c, admin_invited.user, user_c, user_invited.user


def _wait_for_snapshot(engine, convo_id: str, timeout: float = 3.0) -> int:
    """Poll until a conversation row with messages lands, or timeout."""
    deadline = time.monotonic() + timeout
    n = 0
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            n = conn.execute(
                text("SELECT COUNT(*) FROM messages WHERE conversation_id = :c"),
                {"c": convo_id},
            ).scalar_one()
        if n:
            return n
        time.sleep(0.05)
    return n


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_non_admin_forbidden(user_client):
    client, _ = user_client
    assert client.get("/api/v1/admin/conversations/").status_code == 403
    assert client.get("/api/v1/admin/conversations/xyz").status_code == 403
    assert client.delete("/api/v1/admin/conversations/xyz").status_code == 403


def test_admin_list_empty(admin_client):
    client, _ = admin_client
    r = client.get("/api/v1/admin/conversations/")
    assert r.status_code == 200
    assert r.json() == {"rows": [], "next_cursor": None}


def test_chat_turn_writes_snapshot(fresh_db, patched_pipeline):
    admin_c, _admin, user_c, user = _make_admin_and_user_clients(fresh_db)
    r = user_c.post(
        "/api/v1/chat/poll",
        json={"message": "count rows please", "db_id": "california_schools"},
    )
    assert r.status_code == 200, r.text
    convo_id = r.json()["conversation_id"]

    engine = create_engine(fresh_db)
    n = _wait_for_snapshot(engine, convo_id)
    assert n == 2  # one user + one assistant row

    with engine.connect() as conn:
        conv_row = conn.execute(
            text(
                "SELECT id, user_id, db_id, title FROM conversations WHERE id = :c"
            ),
            {"c": convo_id},
        ).first()
        msg_rows = conn.execute(
            text(
                "SELECT role, content, chunks_json FROM messages "
                "WHERE conversation_id = :c ORDER BY created_at, id"
            ),
            {"c": convo_id},
        ).fetchall()

    assert conv_row is not None
    assert conv_row.user_id == user.id
    assert conv_row.db_id == "california_schools"
    assert conv_row.title == "count rows please"
    roles = sorted(m.role for m in msg_rows)
    assert roles == ["assistant", "user"]
    # Assistant row has chunks_json populated (list of chunk dicts).
    assistant = next(m for m in msg_rows if m.role == "assistant")
    assert assistant.chunks_json
    parsed = json.loads(assistant.chunks_json)
    assert isinstance(parsed, list)
    assert len(parsed) >= 1

    # Admin list includes this conversation with user_email joined.
    lr = admin_c.get("/api/v1/admin/conversations/")
    assert lr.status_code == 200
    body = lr.json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["id"] == convo_id
    assert row["user_email"] == "user@example.com"
    assert row["message_count"] == 2

    # Detail returns parsed chunks_json.
    dr = admin_c.get(f"/api/v1/admin/conversations/{convo_id}")
    assert dr.status_code == 200
    detail = dr.json()
    assert detail["user_email"] == "user@example.com"
    assert len(detail["messages"]) == 2
    assistant_detail = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert isinstance(assistant_detail["chunks_json"], list)
    assert len(assistant_detail["chunks_json"]) >= 1


def test_user_id_filter(fresh_db, patched_pipeline):
    admin_c, _admin, user_c, user = _make_admin_and_user_clients(fresh_db)
    r = user_c.post(
        "/api/v1/chat/poll",
        json={"message": "first", "db_id": "california_schools"},
    )
    convo_id = r.json()["conversation_id"]
    engine = create_engine(fresh_db)
    _wait_for_snapshot(engine, convo_id)

    # Filter by the user → returns row.
    lr = admin_c.get(f"/api/v1/admin/conversations/?user_id={user.id}")
    assert lr.status_code == 200
    assert len(lr.json()["rows"]) == 1

    # Filter by a bogus user → empty.
    lr2 = admin_c.get("/api/v1/admin/conversations/?user_id=nonexistent")
    assert lr2.status_code == 200
    assert lr2.json()["rows"] == []


def test_cursor_pagination(admin_client, fresh_db):
    client, admin = admin_client
    # Insert 25 conversations directly (with incrementing created_at so order is
    # deterministic and distinct).
    engine = create_engine(fresh_db)
    base = int(time.time()) - 10000
    ids: list[str] = []
    with engine.begin() as conn:
        for i in range(25):
            cid = uuid.uuid4().hex
            ids.append(cid)
            conn.execute(
                text(
                    "INSERT INTO conversations "
                    "(id, user_id, db_id, title, is_starred, created_at, updated_at) "
                    "VALUES (:id, :uid, :db, :t, 0, :ct, :ct)"
                ),
                {
                    "id": cid,
                    "uid": admin.id,
                    "db": "test_db",
                    "t": f"title-{i}",
                    "ct": base + i,
                },
            )

    seen: list[str] = []
    r1 = client.get("/api/v1/admin/conversations/?limit=10")
    assert r1.status_code == 200
    b1 = r1.json()
    assert len(b1["rows"]) == 10
    assert b1["next_cursor"] is not None
    seen.extend(row["id"] for row in b1["rows"])

    r2 = client.get(f"/api/v1/admin/conversations/?limit=10&cursor={b1['next_cursor']}")
    b2 = r2.json()
    assert len(b2["rows"]) == 10
    assert b2["next_cursor"] is not None
    assert set(b2["rows"][i]["id"] for i in range(10)).isdisjoint(set(seen))
    seen.extend(row["id"] for row in b2["rows"])

    r3 = client.get(f"/api/v1/admin/conversations/?limit=10&cursor={b2['next_cursor']}")
    b3 = r3.json()
    assert len(b3["rows"]) == 5
    assert b3["next_cursor"] is None
    seen.extend(row["id"] for row in b3["rows"])

    # 25 unique ids accounted for (and they are all from the seeded batch).
    assert len(set(seen)) == 25
    assert set(seen) == set(ids)


def test_delete_cascades_messages(admin_client, fresh_db):
    client, admin = admin_client
    engine = create_engine(fresh_db)
    cid = uuid.uuid4().hex
    now = int(time.time())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO conversations (id, user_id, db_id, title, is_starred, created_at, updated_at) "
                "VALUES (:id, :uid, 'db', 't', 0, :ct, :ct)"
            ),
            {"id": cid, "uid": admin.id, "ct": now},
        )
        for role in ("user", "assistant"):
            conn.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content, created_at) "
                    "VALUES (:id, :cid, :role, 'hi', :ct)"
                ),
                {"id": uuid.uuid4().hex, "cid": cid, "role": role, "ct": now},
            )

    dr = client.delete(f"/api/v1/admin/conversations/{cid}")
    assert dr.status_code == 200
    assert dr.json() == {"deleted": True}

    with engine.connect() as conn:
        n_conv = conn.execute(
            text("SELECT COUNT(*) FROM conversations WHERE id = :c"), {"c": cid}
        ).scalar_one()
        n_msg = conn.execute(
            text("SELECT COUNT(*) FROM messages WHERE conversation_id = :c"),
            {"c": cid},
        ).scalar_one()
    assert n_conv == 0
    assert n_msg == 0

    # Second delete → 404.
    dr2 = client.delete(f"/api/v1/admin/conversations/{cid}")
    assert dr2.status_code == 404
