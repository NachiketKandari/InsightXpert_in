"""Read-only database connector — dialect-dispatched.

The connector itself doesn't know SQL dialects; it calls into the adapter
registered for ``ref.dialect`` for connection-open + write-guard.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .dialects import get_adapter

# Re-exported for callers that need the regex directly (e.g. routes/automations.py
# validates SQL in automation setup before a connector is constructed).
# This is the SQLite-dialect guard; for future multi-dialect callers, use
# get_adapter(dialect).forbidden_sql_re instead.
FORBIDDEN_SQL_RE = re.compile(
    r"(?:\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|"
    r"REVOKE|ATTACH|DETACH)\b)|(?:\bPRAGMA\s+\w+\s*=)",
    re.IGNORECASE,
)


class ForbiddenSQLError(Exception):
    """Raised when the SQL contains a write/DDL statement per dialect guard."""


class SQLTimeoutError(Exception):
    """Raised when a query exceeds the configured timeout."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    execution_time_ms: int


class DatabaseConnector:
    """Per-request connector. Dispatches to the dialect adapter for open + guard."""

    def __init__(self, ref: Any, *, row_limit: int = 1000, timeout_s: int = 30) -> None:
        """``ref`` is a DatabaseRef; Any-typed to avoid circular import."""
        self._ref = ref
        self._adapter = get_adapter(ref.dialect)
        self._row_limit = row_limit
        self._timeout = timeout_s

    def execute(self, sql: str) -> QueryResult:
        if self._adapter.forbidden_sql_re.search(sql):
            raise ForbiddenSQLError("write statements are not allowed")

        start = time.perf_counter()
        con = self._adapter.open_readonly(self._ref)
        try:
            try:
                cursor = con.execute(sql)
            except sqlite3.OperationalError as e:
                if "interrupted" in str(e).lower() or "timeout" in str(e).lower():
                    raise SQLTimeoutError(str(e)) from e
                raise
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [list(r) for r in cursor.fetchmany(self._row_limit)]
            # For SQLite, the adapter set PRAGMA query_only=ON; reset it on success so
            # the (about-to-close) connection state doesn't leak in any pooling scheme.
            if self._ref.dialect == "sqlite":
                con.execute("PRAGMA query_only = OFF")
        finally:
            con.close()

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return QueryResult(columns=columns, rows=rows, execution_time_ms=elapsed_ms)
