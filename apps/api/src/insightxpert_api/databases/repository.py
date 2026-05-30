"""Databases repository — thin SQL layer for the `databases` + `database_shares` tables.

Service layer in :mod:`insightxpert_api.databases.service` consumes these. No
business logic here; visibility rules live one level up.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy import delete as sa_delete

from ..db.engine import get_engine
from .table import database_shares, databases_table

# Columns safe to return to any caller — excludes connection_config_encrypted.
_PUBLIC_COLS = [
    databases_table.c.db_id,
    databases_table.c.owner_user_id,
    databases_table.c.visibility,
    databases_table.c.size_bytes,
    databases_table.c.created_at,
    databases_table.c.kind,
    databases_table.c.pipeline_mode_default,
]


def get(db_id: str) -> dict[str, Any] | None:
    """Return public columns for *db_id*, or None.  The encrypted connection
    config is NOT included — use :func:`get_with_config` when you need it."""
    with get_engine().connect() as conn:
        row = conn.execute(
            select(*_PUBLIC_COLS).where(databases_table.c.db_id == db_id)
        ).first()
    return dict(row._mapping) if row else None


def get_with_config(db_id: str) -> dict[str, Any] | None:
    """Like :func:`get` but includes ``connection_config_encrypted``.
    Only call this when you actually need to decrypt and use the connection
    string (e.g. DatabaseService.resolve_connector)."""
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
    *,
    kind: str = "sqlite_file",
    connection_config_encrypted: str | None = None,
) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            insert(databases_table).values(
                db_id=db_id,
                owner_user_id=owner_user_id,
                visibility=visibility,
                size_bytes=size_bytes,
                created_at=int(time.time()),
                kind=kind,
                connection_config_encrypted=connection_config_encrypted,
            )
        )


def upsert_private(
    db_id: str,
    owner_user_id: str,
    size_bytes: int,
    *,
    kind: str = "sqlite_file",
    connection_config_encrypted: str | None = None,
) -> None:
    """Insert a row if missing, otherwise update owner + size (+kind/config).

    Used by the upload route (sqlite_file) and by the BYO-DB connections route
    (postgres/libsql) so re-saving an existing db_id re-anchors ownership
    without duplicating rows. Visibility defaults to 'private' on first
    insert and is preserved on subsequent upserts.
    """
    existing = get(db_id)
    if existing is None:
        insert_db(
            db_id,
            owner_user_id,
            "private",
            size_bytes,
            kind=kind,
            connection_config_encrypted=connection_config_encrypted,
        )
        return
    values: dict[str, Any] = {
        "owner_user_id": owner_user_id,
        "size_bytes": size_bytes,
        "kind": kind,
    }
    if connection_config_encrypted is not None:
        values["connection_config_encrypted"] = connection_config_encrypted
    with get_engine().begin() as conn:
        conn.execute(
            update(databases_table)
            .where(databases_table.c.db_id == db_id)
            .values(**values)
        )


def list_owned(owner_user_id: str) -> list[dict[str, Any]]:
    """All databases registered to this owner (any visibility)."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(databases_table).where(
                databases_table.c.owner_user_id == owner_user_id
            )
        ).all()
    return [dict(r._mapping) for r in rows]


def list_owner_map() -> dict[str, str | None]:
    """Return ``{db_id: owner_user_id}`` for every row in the ``databases`` table.

    Used by the list endpoint so the FE can gate owner-only actions without an
    extra round-trip per database.
    """
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(
                databases_table.c.db_id,
                databases_table.c.owner_user_id,
            )
        ).all()
    return {r.db_id: r.owner_user_id for r in rows}


def delete(db_id: str) -> bool:
    """Delete a row and any rows in database_shares. Returns True if deleted."""
    with get_engine().begin() as conn:
        conn.execute(
            sa_delete(database_shares).where(database_shares.c.db_id == db_id)
        )
        result = conn.execute(
            sa_delete(databases_table).where(databases_table.c.db_id == db_id)
        )
        return bool(result.rowcount)


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


def list_all_admin() -> list[dict[str, Any]]:
    """All DBs with owner email + share list. Admin view only.

    Two queries + in-Python merge keeps the shape obvious: ``databases``
    LEFT JOIN ``users`` for ``owner_email``, then a grouping query over
    ``database_shares`` JOIN ``users`` to build ``shared_with`` per DB.
    """
    from ..users.table import users as users_table

    with get_engine().connect() as conn:
        main_rows = conn.execute(
            select(
                databases_table.c.db_id,
                databases_table.c.owner_user_id,
                databases_table.c.visibility,
                databases_table.c.size_bytes,
                databases_table.c.created_at,
                databases_table.c.pipeline_mode_default,
                users_table.c.email.label("owner_email"),
            ).select_from(
                databases_table.outerjoin(
                    users_table,
                    users_table.c.id == databases_table.c.owner_user_id,
                )
            )
        ).all()
        share_rows = conn.execute(
            select(
                database_shares.c.db_id,
                database_shares.c.user_id,
                users_table.c.email,
            ).select_from(
                database_shares.outerjoin(
                    users_table, users_table.c.id == database_shares.c.user_id
                )
            )
        ).all()

    shares_by_db: dict[str, list[dict[str, Any]]] = {}
    for sr in share_rows:
        shares_by_db.setdefault(sr.db_id, []).append(
            {"user_id": sr.user_id, "email": sr.email}
        )

    out: list[dict[str, Any]] = []
    for r in main_rows:
        out.append(
            {
                "db_id": r.db_id,
                "owner_user_id": r.owner_user_id,
                "owner_email": r.owner_email,
                "visibility": r.visibility,
                "size_bytes": r.size_bytes,
                "created_at": r.created_at,
                "pipeline_mode_default": r.pipeline_mode_default,
                "shared_with": shares_by_db.get(r.db_id, []),
            }
        )
    return out


def set_pipeline_mode_default(db_id: str, mode: str | None) -> bool:
    """Update the per-DB ``pipeline_mode_default`` column.

    ``mode`` may be ``"linked"``, ``"full_schema"``, or ``None`` (clear the
    override so the row inherits the system default ``"linked"``). Returns
    ``True`` on success, ``False`` if the ``db_id`` does not exist.
    """
    with get_engine().begin() as conn:
        result = conn.execute(
            update(databases_table)
            .where(databases_table.c.db_id == db_id)
            .values(pipeline_mode_default=mode)
        )
        return bool(result.rowcount)


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
            sa_delete(database_shares).where(database_shares.c.db_id == db_id)
        )
        if visibility == "shared" and shared_with:
            conn.execute(
                insert(database_shares),
                [
                    {"db_id": db_id, "user_id": uid, "created_at": now}
                    for uid in shared_with
                ],
            )
