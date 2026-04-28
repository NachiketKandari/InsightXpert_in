"""Thin SQLAlchemy Core repo for ``shared_snapshots``.

Caller serializes the payload to JSON; this module never imports the
DTO models.
"""

from __future__ import annotations

import time

from sqlalchemy import select, update

from ..db.engine import get_engine
from .table import shared_snapshots


def insert(
    *,
    token: str,
    conversation_id: str,
    owner_user_id: str,
    db_id: str | None,
    db_kind: str,
    title: str | None,
    payload_json: str,
    created_at: int,
    expires_at: int | None,
) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            shared_snapshots.insert().values(
                token=token,
                conversation_id=conversation_id,
                owner_user_id=owner_user_id,
                db_id=db_id,
                db_kind=db_kind,
                title=title,
                payload_json=payload_json,
                created_at=created_at,
                expires_at=expires_at,
                revoked_at=None,
                view_count=0,
            )
        )


def get_by_token(token: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(shared_snapshots).where(shared_snapshots.c.token == token)
        ).mappings().first()
    return dict(row) if row else None


def get_by_conversation(conversation_id: str, owner_user_id: str) -> dict | None:
    """Return the most recent non-revoked snapshot for a conversation owned
    by ``owner_user_id``, or None. Used by the FE to show "already shared"."""
    with get_engine().connect() as conn:
        row = conn.execute(
            select(shared_snapshots)
            .where(shared_snapshots.c.conversation_id == conversation_id)
            .where(shared_snapshots.c.owner_user_id == owner_user_id)
            .where(shared_snapshots.c.revoked_at.is_(None))
            .order_by(shared_snapshots.c.created_at.desc())
            .limit(1)
        ).mappings().first()
    return dict(row) if row else None


def list_by_owner(owner_user_id: str) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(shared_snapshots)
            .where(shared_snapshots.c.owner_user_id == owner_user_id)
            .order_by(shared_snapshots.c.created_at.desc())
        ).mappings().all()
    return [dict(r) for r in rows]


def revoke(token: str) -> int:
    """Set ``revoked_at`` if not already set. Returns affected row count."""
    now = int(time.time())
    with get_engine().begin() as conn:
        result = conn.execute(
            update(shared_snapshots)
            .where(shared_snapshots.c.token == token)
            .where(shared_snapshots.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    return result.rowcount or 0


def increment_view(token: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            update(shared_snapshots)
            .where(shared_snapshots.c.token == token)
            .values(view_count=shared_snapshots.c.view_count + 1)
        )
