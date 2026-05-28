"""Read-only Postgres query executor for BYO-DB connections.

Two layers of write protection (D3 in the plan — belt + suspenders):

1. ``FORBIDDEN_SQL_RE`` regex — fast pre-flight reject of obvious DDL/DML.
2. ``default_transaction_read_only=on`` set as a session option in
   ``connect_args``. Even if the regex misses something (e.g. ``CREATE TEMP
   TABLE x AS SELECT 1``), Postgres rejects the write before it commits.

We also set ``statement_timeout`` and pin ``search_path`` to the user-chosen
schema so unqualified names resolve there first.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text

from ..db.dialects.forbidden_sql import FORBIDDEN_SQL_RE
from .types import PostgresConnection


_FORBIDDEN_SQL = FORBIDDEN_SQL_RE


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    execution_time_ms: int


class PostgresConnector:
    def __init__(
        self,
        config: PostgresConnection,
        *,
        row_limit: int = 1000,
        timeout_seconds: int = 30,
    ) -> None:
        self._config = config
        self._row_limit = row_limit
        self._timeout_seconds = timeout_seconds
        self._engine = create_engine(
            config.to_dsn(),
            connect_args={
                "options": (
                    f"-c default_transaction_read_only=on "
                    f"-c statement_timeout={timeout_seconds * 1000} "
                    f"-c search_path={config.schema_},public"
                ),
            },
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
        )

    def execute(self, sql: str) -> QueryResult:
        if _FORBIDDEN_SQL.search(sql):
            raise ValueError("read-only: write/DDL statements not allowed")
        start = time.monotonic()
        with self._engine.connect() as conn:
            cur = conn.execute(text(sql))
            rows = cur.fetchmany(self._row_limit)
            columns = list(cur.keys())
        return QueryResult(
            columns=columns,
            rows=[tuple(r) for r in rows],
            execution_time_ms=int((time.monotonic() - start) * 1000),
        )

    def list_tables(self) -> list[str]:
        sql = """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = :schema
            ORDER BY table_name LIMIT 200
        """
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), {"schema": self._config.schema_}).fetchall()
        return [r[0] for r in rows]

    def describe_table(self, name: str) -> list[dict[str, Any]]:
        sql = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :name
            ORDER BY ordinal_position
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(sql),
                {"schema": self._config.schema_, "name": name},
            ).fetchall()
        return [
            {"name": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in rows
        ]

    def dispose(self) -> None:
        """Close all connections in the pool. Safe to call multiple times."""
        self._engine.dispose()
