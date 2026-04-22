"""Port a SQLite database into a Postgres schema.

Purpose: seed the ``toxicology_pg`` database in Supabase from the bundled
``apps/api/Databases/_shared/toxicology.sqlite`` file. Narrow scope — tables,
columns, primary keys, foreign keys, rows. No views, triggers, sequences, or
stored procedures. Toxicology fits this subset; if a future BIRD DB exercises
more, extend then.

Usage::

    python -m insightxpert_api.scripts.sqlite_to_postgres \\
        --sqlite apps/api/Databases/_shared/toxicology.sqlite \\
        --pg-url "$DATABASE_URL_TOXICOLOGY_PG" \\
        --pg-schema toxicology \\
        --drop-existing
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql as pg_sql

log = logging.getLogger(__name__)

# SQLite affinity → Postgres type mapping. Narrow by design; unknown affinities
# fall through to TEXT, which is safe but may be too permissive for numerics —
# add a row-count sanity check at the end to catch silent data loss.
_TYPE_MAP = {
    "INTEGER": "BIGINT",
    "INT": "BIGINT",
    "REAL": "DOUBLE PRECISION",
    "FLOAT": "DOUBLE PRECISION",
    "NUMERIC": "NUMERIC",
    "DECIMAL": "NUMERIC",
    "TEXT": "TEXT",
    "VARCHAR": "TEXT",
    "CHAR": "TEXT",
    "BLOB": "BYTEA",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP",
    "TIMESTAMP": "TIMESTAMP",
}


def _pg_type(sqlite_type: str | None) -> str:
    if not sqlite_type:
        return "TEXT"
    key = sqlite_type.strip().upper().split("(")[0]
    return _TYPE_MAP.get(key, "TEXT")


def convert(
    *,
    sqlite_path: Path,
    pg_url: str,
    pg_schema: str,
    drop_existing: bool,
) -> None:
    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row

    with psycopg.connect(pg_url, autocommit=False) as dst:
        with dst.cursor() as cur:
            if drop_existing:
                cur.execute(
                    pg_sql.SQL("DROP SCHEMA IF EXISTS {s} CASCADE").format(
                        s=pg_sql.Identifier(pg_schema)
                    )
                )
            cur.execute(
                pg_sql.SQL("CREATE SCHEMA {s}").format(
                    s=pg_sql.Identifier(pg_schema)
                )
            )
            cur.execute(
                pg_sql.SQL("SET search_path TO {s}").format(
                    s=pg_sql.Identifier(pg_schema)
                )
            )

            tables = [
                r[0]
                for r in src.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                ).fetchall()
            ]
            log.info("tables_found count=%d", len(tables))

            for tname in tables:
                _create_table(cur, tname, src, pg_schema)
                _copy_rows(cur, tname, src, pg_schema)

            for tname in tables:
                _add_fks(cur, tname, src, pg_schema)

            dst.commit()

            # Sanity check: row counts must match. Runs inside the same cursor
            # as the writes, so any commit ordering issue would surface here.
            for tname in tables:
                src_count = src.execute(
                    f'SELECT COUNT(*) FROM "{tname}"'
                ).fetchone()[0]
                cur.execute(
                    pg_sql.SQL("SELECT COUNT(*) FROM {s}.{t}").format(
                        s=pg_sql.Identifier(pg_schema),
                        t=pg_sql.Identifier(tname),
                    )
                )
                dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    raise RuntimeError(
                        f"Row count mismatch in {tname}: "
                        f"sqlite={src_count}, pg={dst_count}"
                    )
                log.info("table_ok name=%s rows=%d", tname, src_count)

    src.close()
    log.info("conversion_complete schema=%s tables=%d", pg_schema, len(tables))


def _create_table(
    cur: Any, tname: str, src: sqlite3.Connection, pg_schema: str
) -> None:
    pragma = src.execute(f'PRAGMA table_info("{tname}")').fetchall()
    col_defs = []
    pk_cols = []
    for row in pragma:
        name = row["name"]
        col_type = _pg_type(row["type"])
        notnull = "NOT NULL" if row["notnull"] else ""
        col_defs.append(f'"{name}" {col_type} {notnull}'.strip())
        if row["pk"]:
            pk_cols.append((row["pk"], name))
    pk_cols.sort()
    pk_clause = (
        ", PRIMARY KEY (" + ", ".join(f'"{n}"' for _, n in pk_cols) + ")"
        if pk_cols
        else ""
    )
    ddl = (
        f'CREATE TABLE "{pg_schema}"."{tname}" ('
        + ", ".join(col_defs)
        + pk_clause
        + ")"
    )
    cur.execute(ddl)


def _copy_rows(
    cur: Any, tname: str, src: sqlite3.Connection, pg_schema: str
) -> None:
    pragma = src.execute(f'PRAGMA table_info("{tname}")').fetchall()
    cols = [row["name"] for row in pragma]
    col_list = ", ".join(f'"{c}"' for c in cols)

    copy_stmt = pg_sql.SQL("COPY {s}.{t} ({cols}) FROM STDIN").format(
        s=pg_sql.Identifier(pg_schema),
        t=pg_sql.Identifier(tname),
        cols=pg_sql.SQL(col_list),
    )
    with cur.copy(copy_stmt) as copy:
        for row in src.execute(f'SELECT * FROM "{tname}"'):
            copy.write_row(tuple(row))


def _add_fks(
    cur: Any, tname: str, src: sqlite3.Connection, pg_schema: str
) -> None:
    fks = src.execute(f'PRAGMA foreign_key_list("{tname}")').fetchall()
    for fk in fks:
        ref_tab = fk["table"]
        from_col = fk["from"]
        to_col = fk["to"]
        if to_col is None:
            # Implicit PK reference — resolve.
            pk_pragma = src.execute(
                f'PRAGMA table_info("{ref_tab}")'
            ).fetchall()
            pks = [r["name"] for r in pk_pragma if r["pk"]]
            if not pks:
                log.warning(
                    "fk_skipped table=%s from=%s ref=%s (no PK)",
                    tname, from_col, ref_tab,
                )
                continue
            to_col = pks[0]
        cur.execute(
            f'ALTER TABLE "{pg_schema}"."{tname}" '
            f'ADD FOREIGN KEY ("{from_col}") '
            f'REFERENCES "{pg_schema}"."{ref_tab}" ("{to_col}")'
        )


def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--sqlite", required=True, type=Path)
    p.add_argument("--pg-url", required=True)
    p.add_argument("--pg-schema", required=True)
    p.add_argument("--drop-existing", action="store_true")
    args = p.parse_args()

    if not args.sqlite.exists():
        log.error("sqlite_file_not_found path=%s", args.sqlite)
        return 2

    convert(
        sqlite_path=args.sqlite,
        pg_url=args.pg_url,
        pg_schema=args.pg_schema,
        drop_existing=args.drop_existing,
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
