"""Oracle schema extractor — reads ``ALL_*`` dictionary views.

Returns the same ``DatabaseSchema`` dataclass the SQLite/Postgres extractors
use, so downstream code (schema linker, prompt rendering) is dialect-agnostic.
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
SELECT table_name FROM all_tables
WHERE owner = :owner
ORDER BY table_name
"""

_COLUMNS_SQL = """
SELECT column_name, data_type, nullable, data_default
FROM all_tab_columns
WHERE owner = :owner AND table_name = :table
ORDER BY column_id
"""

_PK_SQL = """
SELECT acc.column_name
FROM all_constraints ac
JOIN all_cons_columns acc
  ON ac.owner = acc.owner
 AND ac.constraint_name = acc.constraint_name
WHERE ac.constraint_type = 'P'
  AND ac.owner = :owner
  AND ac.table_name = :table
"""

_FKS_SQL = """
SELECT acc.column_name, ac.r_owner, ac.r_constraint_name
FROM all_constraints ac
JOIN all_cons_columns acc
  ON ac.owner = acc.owner
 AND ac.constraint_name = acc.constraint_name
WHERE ac.constraint_type = 'R'
  AND ac.owner = :owner
  AND ac.table_name = :table
ORDER BY acc.position
"""

_REF_COLS_SQL = """
SELECT acc.table_name, acc.column_name
FROM all_constraints ac
JOIN all_cons_columns acc
  ON ac.owner = acc.owner
 AND ac.constraint_name = acc.constraint_name
WHERE ac.owner = :owner
  AND ac.constraint_name = :cname
ORDER BY acc.position
"""


def _fetch(conn: Any, sql: str, params: dict) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def extract_oracle_schema(
    conn: Any,
    owner: str,
    selected_tables: list[str] | None = None,
) -> DatabaseSchema:
    """Extract a DatabaseSchema for ``owner`` (already uppercased).

    ``conn`` is a DB-API connection (e.g. ``OracleDatabase.conn`` or the raw
    oracledb connection). All identifiers come from callers via bind
    parameters; never string-concat user input into these SQL bodies.

    When ``selected_tables`` is non-empty, only those tables are extracted
    (the connect dialog's table picker allowlist).
    """
    owner = owner.strip().upper()
    table_rows = _fetch(conn, _TABLES_SQL, {"owner": owner})
    names = [r[0] for r in table_rows]
    if selected_tables:
        wanted = {t.upper() for t in selected_tables}
        names = [t for t in names if t.upper() in wanted]

    tables: list[TableSchema] = []
    for tname in names:
        col_rows = _fetch(conn, _COLUMNS_SQL, {"owner": owner, "table": tname})
        pk_cols = {
            r[0] for r in _fetch(conn, _PK_SQL, {"owner": owner, "table": tname})
        }
        fk_rows = _fetch(conn, _FKS_SQL, {"owner": owner, "table": tname})

        columns = [
            ColumnSchema(
                name=name,
                type=(dtype or "TEXT").upper(),
                nullable=(nullable == "Y"),
                primary_key=(name in pk_cols),
                default=str(default).strip() if default is not None else None,
            )
            for (name, dtype, nullable, default) in col_rows
        ]

        foreign_keys = []
        for from_col, ref_owner, ref_cname in fk_rows:
            ref_rows = _fetch(
                conn, _REF_COLS_SQL, {"owner": ref_owner, "cname": ref_cname}
            )
            ref_table = ref_rows[0][0] if ref_rows else ""
            ref_col = ref_rows[0][1] if ref_rows else ""
            foreign_keys.append(
                ForeignKey(
                    column=from_col,
                    ref_table=ref_table,
                    ref_column=ref_col,
                    on_delete=None,
                    on_update=None,
                )
            )
        tables.append(
            TableSchema(name=tname, columns=columns, foreign_keys=foreign_keys)
        )

    return DatabaseSchema(db_id=owner, tables=tables)
