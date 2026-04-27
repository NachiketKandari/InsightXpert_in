"""Sanity check that the BYO-DB migration adds the required columns."""

from __future__ import annotations


def test_databases_has_connection_columns(fresh_db):
    from sqlalchemy import inspect

    from insightxpert_api.db.engine import get_engine

    insp = inspect(get_engine())
    cols = {c["name"] for c in insp.get_columns("databases")}
    assert "kind" in cols
    assert "connection_config_encrypted" in cols


def test_kind_default_is_sqlite_file(fresh_db):
    """Existing INSERTs that don't specify `kind` should default to sqlite_file."""
    import time

    from sqlalchemy import insert, select, text

    from insightxpert_api.databases.table import databases_table
    from insightxpert_api.db.engine import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            insert(databases_table).values(
                db_id="legacy_db",
                owner_user_id=None,
                visibility="public",
                size_bytes=0,
                created_at=int(time.time()),
            )
        )
    with engine.connect() as conn:
        row = conn.execute(
            select(databases_table.c.kind).where(databases_table.c.db_id == "legacy_db")
        ).first()
    assert row is not None
    assert row[0] == "sqlite_file"
    # silence ruff for unused import
    _ = text
