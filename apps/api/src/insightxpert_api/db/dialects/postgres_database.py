"""Database interface implementation for Postgres.

Satisfies the vendored ``Database`` ABC (execute + close + context manager) so
the profiler can treat Postgres DBs the same as SQLite ones.
"""
from __future__ import annotations

from typing import Any

import psycopg

from ...vendored.pipeline_core.db import Database


class PostgresDatabase(Database):
    """Vendored-Database wrapper around a psycopg read-only connection."""

    def __init__(self, ref: Any) -> None:
        if not ref.connection_url:
            raise ValueError(f"Postgres ref {ref.db_id!r} missing connection_url")
        self.db_id = ref.db_id
        self._conn = psycopg.connect(
            ref.connection_url,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=30000"
            ),
            autocommit=True,
        )

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            return list(cur.fetchall())

    def close(self) -> None:
        self._conn.close()
