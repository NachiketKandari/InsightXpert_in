"""Databases repository — thin SQL layer for the `databases` + `database_shares` tables.

Service layer in :mod:`insightxpert_api.databases.service` consumes these. No
business logic here; visibility rules live one level up.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import and_, delete, insert, or_, select, update

from ..db.engine import get_engine
from .table import database_shares, databases_table


def get(db_id: str) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(databases_table).where(databases_table.c.db_id == db_id)
        ).first()
    return dict(row._mapping) if row else None


def insert_db(
    db_id: str,
    owner_user_id: str | None,
    visibility: str,
    size_bytes: int,
) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            insert(databases_table).values(
                db_id=db_id,
                owner_user_id=owner_user_id,
                visibility=visibility,
                size_bytes=size_bytes,
                created_at=int(time.time()),
            )
        )


def upsert_private(db_id: str, owner_user_id: str, size_bytes: int) -> None:
    """Insert a row if missing, otherwise update owner + size.

    Used by the upload route so re-uploading an existing db_id re-anchors
    ownership without duplicating rows. Visibility defaults to 'private'
    on first insert and is preserved on subsequent upserts.
    """
    existing = get(db_id)
    if existing is None:
        insert_db(db_id, owner_user_id, "private", size_bytes)
        return
    with get_engine().begin() as conn:
        conn.execute(
            update(databases_table)
            .where(databases_table.c.db_id == db_id)
            .values(owner_user_id=owner_user_id, size_bytes=size_bytes)
        )


def list_visible(user_id: str, is_admin: bool) -> list[dict[str, Any]]:
    """Admin sees all. Non-admin sees public ∪ owned ∪ shared."""
    with get_engine().connect() as conn:
        if is_admin:
            rows = conn.execute(select(databases_table)).all()
        else:
            shared_ids = select(database_shares.c.db_id).where(
                database_shares.c.user_id == user_id
            )
            rows = conn.execute(
                select(databases_table).where(
                    or_(
                        databases_table.c.visibility == "public",
                        databases_table.c.owner_user_id == user_id,
                        and_(
                            databases_table.c.visibility == "shared",
                            databases_table.c.db_id.in_(shared_ids),
                        ),
                    )
                )
            ).all()
    return [dict(r._mapping) for r in rows]


def set_visibility(
    db_id: str, visibility: str, shared_with: list[str] | None
) -> None:
    """Update visibility and atomically replace the share list.

    A single transaction: bump visibility, wipe existing shares, re-insert
    any new shares (only if visibility='shared' and shared_with non-empty).
    """
    now = int(time.time())
    with get_engine().begin() as conn:
        conn.execute(
            update(databases_table)
            .where(databases_table.c.db_id == db_id)
            .values(visibility=visibility)
        )
        conn.execute(
            delete(database_shares).where(database_shares.c.db_id == db_id)
        )
        if visibility == "shared" and shared_with:
            conn.execute(
                insert(database_shares),
                [
                    {"db_id": db_id, "user_id": uid, "created_at": now}
                    for uid in shared_with
                ],
            )
