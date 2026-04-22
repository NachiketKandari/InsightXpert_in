"""SQLite adapter — lift-and-shift of the pre-adapter code paths.

No behavior change from the pre-dialect code. Regex + PRAGMA wrapping both
come straight from ``db/connector.py``.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from ...vendored.pipeline_core.db import SQLiteDatabase
from ...vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor
from . import DIALECTS
from .base import DialectAdapter, ProfilingQueryPack

# Two patterns ORed. PRAGMA=write is split out so the trailing \b only applies to
# the keyword variant (PRAGMA foo = bar ends on non-word chars, which would fail \b).
FORBIDDEN_SQL_RE = re.compile(
    r"(?:\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|"
    r"REVOKE|ATTACH|DETACH)\b)|(?:\bPRAGMA\s+\w+\s*=)",
    re.IGNORECASE,
)

_PROFILING = ProfilingQueryPack(
    null_count='SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL',
    distinct_count='SELECT COUNT(DISTINCT "{col}") FROM "{table}"',
    min_max='SELECT MIN("{col}"), MAX("{col}") FROM "{table}"',
    sample_rows='SELECT "{col}" FROM "{table}" ORDER BY RANDOM() LIMIT 100',
)


class SqliteAdapter:
    name = "sqlite"
    sqlglot_dialect = "sqlite"
    prompt_variant = "sqlite"
    forbidden_sql_re = FORBIDDEN_SQL_RE

    def open_readonly(self, ref: Any) -> sqlite3.Connection:
        if ref.local_path is None:
            raise ValueError(f"SQLite ref {ref.db_id!r} missing local_path")
        con = sqlite3.connect(ref.local_path, timeout=30)
        con.execute("PRAGMA query_only = ON")
        return con

    def teardown_readonly(self, conn: sqlite3.Connection) -> None:
        """Reset PRAGMA query_only so the closing connection can't leak state."""
        conn.execute("PRAGMA query_only = OFF")

    def is_timeout_error(self, exc: BaseException) -> bool:
        """SQLite surfaces timeouts/interrupts via OperationalError."""
        if not isinstance(exc, sqlite3.OperationalError):
            return False
        msg = str(exc).lower()
        return "interrupted" in msg or "timeout" in msg

    def extract_schema(self, conn: Any) -> Any:
        """Schema extraction via the vendored SQLiteDatabase wrapper.

        Expects a vendored SQLiteDatabase instance (not a raw sqlite3.Connection).
        Downstream callers that have only a raw connection should wrap.
        """
        if isinstance(conn, SQLiteDatabase):
            db = conn
        else:
            raise TypeError(
                "SqliteAdapter.extract_schema expects a SQLiteDatabase; "
                "got a raw sqlite3.Connection. Use open_readonly() + a wrapper."
            )
        return SchemaExtractor().extract(db)

    def profiling_queries(self) -> ProfilingQueryPack:
        return _PROFILING


# Register at import.
DIALECTS["sqlite"] = SqliteAdapter()
