"""Postgres schema extractor — reads ``information_schema``.

Returns the same ``DatabaseSchema`` dataclass the SQLite extractor uses, so
downstream code (schema linker, prompt rendering) is dialect-agnostic.
"""
from __future__ import annotations

from typing import Any

from ...vendored.pipeline_core.models.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKey,
    TableSchema,
)


_TABLES_SQL = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = %s
  AND table_type = 'BASE TABLE'
ORDER BY table_name
"""

_COLUMNS_SQL = """
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = %s AND table_name = %s
ORDER BY ordinal_position
"""

_PK_SQL = """
SELECT kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema = %s
  AND tc.table_name = %s
"""

_FKS_SQL = """
SELECT
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name  AS ref_table,
    ccu.column_name AS ref_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name
 AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = %s
  AND tc.table_name = %s
ORDER BY tc.constraint_name
"""


def extract_postgres_schema(conn: Any, schema_name: str = "toxicology") -> DatabaseSchema:
    """Extract a DatabaseSchema from a Postgres connection.

    Uses a single cursor and runs 1 + 3N queries (one to list tables, then
    columns / PKs / FKs per table). All identifiers come from callers via
    parameterized queries; never string-concat user input into these SQL bodies.
    """
    with conn.cursor() as cur:
        cur.execute(_TABLES_SQL, (schema_name,))
        table_rows = cur.fetchall()

        tables: list[TableSchema] = []
        for (tname,) in table_rows:
            cur.execute(_COLUMNS_SQL, (schema_name, tname))
            col_rows = cur.fetchall()

            cur.execute(_PK_SQL, (schema_name, tname))
            pk_cols = {r[0] for r in cur.fetchall()}

            cur.execute(_FKS_SQL, (schema_name, tname))
            fk_rows = cur.fetchall()

            columns = [
                ColumnSchema(
                    name=name,
                    type=(dtype or "TEXT").upper(),
                    nullable=(nullable == "YES"),
                    primary_key=(name in pk_cols),
                    default=str(default) if default is not None else None,
                )
                for (name, dtype, nullable, default) in col_rows
            ]
            foreign_keys = [
                ForeignKey(
                    column=from_col,
                    ref_table=ref_table,
                    ref_column=ref_column,
                    on_delete=None,
                    on_update=None,
                )
                for (_cname, _tname, from_col, ref_table, ref_column) in fk_rows
            ]
            tables.append(
                TableSchema(name=tname, columns=columns, foreign_keys=foreign_keys)
            )

    return DatabaseSchema(db_id=schema_name, tables=tables)
