"""Read-only SQLite connector.

Port of ``public/InsightXpert/backend/src/insightxpert/db/connector.py`` — keeps the two
load-bearing correctness details:

1. ``FORBIDDEN_SQL_RE`` — regex that blocks write statements before they touch the DB. Belt for
   defense-in-depth; the PRAGMA below is the suspenders.
2. ``PRAGMA query_only = ON`` wrapped in ``try/finally`` so pooled/shared connections can't be
   left in read-only state if a query raises. SQLite specific; fine, since v1 is SQLite-only.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

FORBIDDEN_SQL_RE = re.compile(
    # Two patterns ORed together. The PRAGMA-write case is split out so the trailing \b
    # boundary only applies to the keyword variant — `PRAGMA foo = bar` ends on non-word
    # characters which would otherwise fail the word boundary check.
    r"(?:\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|"
    r"REVOKE|ATTACH|DETACH)\b)|(?:\bPRAGMA\s+\w+\s*=)",
    re.IGNORECASE,
)


class ForbiddenSQLError(Exception):
    """Raised when the SQL contains a write/DDL/PRAGMA-write statement."""


class SQLTimeoutError(Exception):
    """Raised when a query exceeds the configured timeout."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    execution_time_ms: int


class DatabaseConnector:
    """Per-request connector. Cheap to construct — no pooling for v1."""

    def __init__(self, path: str, *, row_limit: int = 1000, timeout_s: int = 30) -> None:
        self._path = path
        self._row_limit = row_limit
        self._timeout = timeout_s

    def execute(self, sql: str) -> QueryResult:
        """Execute ``sql`` read-only. Raises ``ForbiddenSQLError`` on write attempts."""
        if FORBIDDEN_SQL_RE.search(sql):
            raise ForbiddenSQLError("write statements are not allowed")

        start = time.perf_counter()
        con = sqlite3.connect(self._path, timeout=self._timeout)
        try:
            con.execute("PRAGMA query_only = ON")
            try:
                try:
                    cursor = con.execute(sql)
                except sqlite3.OperationalError as e:
                    if "interrupted" in str(e).lower() or "timeout" in str(e).lower():
                        raise SQLTimeoutError(str(e)) from e
                    raise
                columns = [d[0] for d in cursor.description] if cursor.description else []
                rows = [list(r) for r in cursor.fetchmany(self._row_limit)]
            finally:
                # CRITICAL: reset PRAGMA so this SQLite file's connection state doesn't leak
                # into subsequent queries if the connection is somehow reused.
                con.execute("PRAGMA query_only = OFF")
        finally:
            con.close()

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return QueryResult(columns=columns, rows=rows, execution_time_ms=elapsed_ms)
