"""Persistence layer for ``database_profiles`` and ``profile_overrides``.

Thin repo on top of SQLAlchemy tables. Caller serializes the
``DatabaseProfile`` to JSON; this module never imports the model.
"""

from __future__ import annotations

import time

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db.engine import get_engine
from .table import database_profiles, profile_overrides


def upsert(
    *,
    db_id: str,
    profile_json: str,
    profile_kind: str = "base",
    owner_user_id: str | None = None,
    generated_by: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Insert-or-replace a profile row keyed by (db_id, profile_kind)."""
    now = int(time.time())
    engine = get_engine()
    is_pg = engine.dialect.name == "postgresql"
    insert = pg_insert if is_pg else sqlite_insert

    stmt = insert(database_profiles).values(
        db_id=db_id,
        profile_kind=profile_kind,
        owner_user_id=owner_user_id,
        profile_json=profile_json,
        generated_at=now,
        generated_by=generated_by,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["db_id", "profile_kind"],
        set_={
            "owner_user_id": stmt.excluded.owner_user_id,
            "profile_json": stmt.excluded.profile_json,
            "generated_at": stmt.excluded.generated_at,
            "generated_by": stmt.excluded.generated_by,
            "input_tokens": stmt.excluded.input_tokens,
            "output_tokens": stmt.excluded.output_tokens,
            "cost_usd": stmt.excluded.cost_usd,
        },
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def get(db_id: str, profile_kind: str = "base") -> dict | None:
    """Fetch a profile row. Returns the row dict or None."""
    with get_engine().connect() as conn:
        row = conn.execute(
            select(database_profiles).where(
                database_profiles.c.db_id == db_id,
                database_profiles.c.profile_kind == profile_kind,
            )
        ).mappings().first()
    return dict(row) if row else None


def exists(db_id: str, profile_kind: str = "base") -> bool:
    return get(db_id, profile_kind) is not None


def list_db_ids(profile_kind: str = "base") -> set[str]:
    """Return the set of db_ids that have a profile row for the given kind.

    Single SELECT, returns just the id column — used by the databases list
    endpoint to set ``has_profile`` per item without N round-trips.
    """
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(database_profiles.c.db_id).where(
                database_profiles.c.profile_kind == profile_kind,
            )
        ).all()
    return {r[0] for r in rows}


def list_summaries(profile_kind: str = "base") -> dict[str, dict[str, int]]:
    """Return ``{db_id: {table_count, column_count, row_count}}`` for every
    profile row of the given kind.

    Replaces N per-card ``GET /databases/{id}/profile`` calls with one DB
    round-trip + Python-side JSON parse. Caller filters by visibility.
    """
    import json

    with get_engine().connect() as conn:
        rows = conn.execute(
            select(
                database_profiles.c.db_id,
                database_profiles.c.profile_json,
            ).where(
                database_profiles.c.profile_kind == profile_kind,
            )
        ).all()

    out: dict[str, dict[str, int]] = {}
    for db_id, profile_json in rows:
        try:
            tables = json.loads(profile_json).get("tables", [])
        except (json.JSONDecodeError, AttributeError):
            continue
        column_count = 0
        row_count = 0
        for t in tables:
            cols = t.get("columns") or []
            column_count += len(cols)
            row_count += int(t.get("row_count") or 0)
        out[db_id] = {
            "table_count": len(tables),
            "column_count": column_count,
            "row_count": row_count,
        }
    return out


def set_join_graph(
    db_id: str,
    join_graph_json: str,
    profile_kind: str = "base",
) -> None:
    """Persist a join graph for a database profile."""
    engine = get_engine()
    stmt = (
        database_profiles.update()
        .where(
            database_profiles.c.db_id == db_id,
            database_profiles.c.profile_kind == profile_kind,
        )
        .values(join_graph_json=join_graph_json)
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def get_join_graph(db_id: str, profile_kind: str = "base") -> str | None:
    """Fetch the join graph JSON for a database profile, or None."""
    with get_engine().connect() as conn:
        row = conn.execute(
            select(database_profiles.c.join_graph_json).where(
                database_profiles.c.db_id == db_id,
                database_profiles.c.profile_kind == profile_kind,
            )
        ).first()
    return row[0] if row and row[0] else None


def set_user_hints(
    db_id: str,
    user_hints: str,
    profile_kind: str = "base",
) -> None:
    """Persist user hints for a database profile.

    Upserts a row even when no profile exists yet — users can set hints
    before running profiling.
    """
    now = int(time.time())
    engine = get_engine()
    is_pg = engine.dialect.name == "postgresql"
    insert = pg_insert if is_pg else sqlite_insert

    stmt = insert(database_profiles).values(
        db_id=db_id,
        profile_kind=profile_kind,
        user_hints=user_hints,
        generated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["db_id", "profile_kind"],
        set_={"user_hints": stmt.excluded.user_hints},
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def get_user_hints(db_id: str, profile_kind: str = "base") -> str | None:
    """Fetch user hints for a database profile, or None."""
    with get_engine().connect() as conn:
        row = conn.execute(
            select(database_profiles.c.user_hints).where(
                database_profiles.c.db_id == db_id,
                database_profiles.c.profile_kind == profile_kind,
            )
        ).first()
    return row[0] if row and row[0] else None


# ---------------------------------------------------------------------------
# Profile overrides — user edits to individual column fields
# ---------------------------------------------------------------------------


def upsert_override(
    *,
    db_id: str,
    table_name: str,
    column_name: str,
    field_path: str,
    value_json: str,
    edited_by: str,
) -> None:
    """Insert or update a single field override."""
    import uuid as _uuid

    now = int(time.time())
    engine = get_engine()
    is_pg = engine.dialect.name == "postgresql"
    insert = pg_insert if is_pg else sqlite_insert

    # Read current row to get or keep the id
    existing = _get_override_row(db_id, table_name, column_name, field_path)
    row_id = existing["id"] if existing else str(_uuid.uuid4())

    stmt = insert(profile_overrides).values(
        id=row_id,
        db_id=db_id,
        table_name=table_name,
        column_name=column_name,
        field_path=field_path,
        value_json=value_json,
        edited_by=edited_by,
        edited_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["db_id", "table_name", "column_name", "field_path"],
        set_={
            "value_json": stmt.excluded.value_json,
            "edited_by": stmt.excluded.edited_by,
            "edited_at": stmt.excluded.edited_at,
        },
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def get_overrides(db_id: str) -> list[dict]:
    """Return all overrides for a db_id."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(profile_overrides).where(
                profile_overrides.c.db_id == db_id,
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def delete_override(
    db_id: str,
    table_name: str,
    column_name: str,
    field_path: str,
) -> int:
    """Delete a single override. Returns rowcount."""
    with get_engine().begin() as conn:
        result = conn.execute(
            delete(profile_overrides).where(
                profile_overrides.c.db_id == db_id,
                profile_overrides.c.table_name == table_name,
                profile_overrides.c.column_name == column_name,
                profile_overrides.c.field_path == field_path,
            )
        )
    return result.rowcount or 0


def _get_override_row(
    db_id: str,
    table_name: str,
    column_name: str,
    field_path: str,
) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(profile_overrides).where(
                profile_overrides.c.db_id == db_id,
                profile_overrides.c.table_name == table_name,
                profile_overrides.c.column_name == column_name,
                profile_overrides.c.field_path == field_path,
            )
        ).mappings().first()
    return dict(row) if row else None


def delete_for_db(db_id: str) -> int:
    """Drop every profile_kind row for a given db_id. Returns rowcount."""
    with get_engine().begin() as conn:
        result = conn.execute(
            delete(database_profiles).where(database_profiles.c.db_id == db_id)
        )
    return result.rowcount or 0
