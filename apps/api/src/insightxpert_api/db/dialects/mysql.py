"""MySQL dialect adapter.

Read-only enforcement via ``read_only=1`` session variable, plus a regex
write-guard as belt-and-suspenders. ANSI_QUOTES sql_mode makes double-quoted
identifiers work (matching sqlglot output).

No TABLESAMPLE in MySQL — profiling uses ``ORDER BY RAND() LIMIT n``.
"""

from __future__ import annotations

import re
from typing import Any

import pymysql

from . import DIALECTS
from .base import DialectAdapter, ProfilingQueryPack
from .forbidden_sql import FORBIDDEN_SQL_RE

_PROFILING = ProfilingQueryPack(
    null_count=(
        'SELECT COUNT(*) FROM `{table}` WHERE `{col}` IS NULL'
    ),
    distinct_count='SELECT COUNT(DISTINCT `{col}`) FROM `{table}`',
    min_max='SELECT MIN(`{col}`), MAX(`{col}`) FROM `{table}`',
    sample_rows='SELECT `{col}` FROM `{table}` ORDER BY RAND() LIMIT 100',
)


class MysqlAdapter:
    name = "mysql"
    sqlglot_dialect = "mysql"
    prompt_variant = "mysql"
    forbidden_sql_re = FORBIDDEN_SQL_RE

    def open_readonly(self, ref: Any) -> pymysql.Connection:
        if not ref.connection_url:
            raise ValueError(f"MySQL ref {ref.db_id!r} missing connection_url")
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(ref.connection_url)
        conn = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/") if parsed.path else "",
            charset=parse_qs(parsed.query).get("charset", ["utf8mb4"])[0],
            read_only=True,
            autocommit=True,
            sql_mode="ANSI_QUOTES,NO_BACKSLASH_ESCAPES",
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        return conn

    def teardown_readonly(self, conn: pymysql.Connection) -> None:
        """No-op on MySQL — read-only is session-scoped, closes with the conn."""

    def is_timeout_error(self, exc: BaseException) -> bool:
        if isinstance(exc, pymysql.err.OperationalError):
            msg = str(exc).lower()
            return "timeout" in msg or "timed out" in msg or "lost connection" in msg or "server has gone away" in msg
        return False

    def open_database(self, ref: Any) -> Any:
        """Return a vendored-ABC Database wrapping a read-only pymysql connection."""
        raise NotImplementedError(
            "MySQL open_database not yet wired — the vendored pipeline ABC "
            "assumes SQLite file paths. Wire a MysqlDatabase ABC wrapper in a "
            "follow-up if full-schema profiling against MySQL is needed."
        )

    def extract_schema(self, db: Any, ref: Any) -> Any:
        raise NotImplementedError(
            "MySQL extract_schema not yet wired. Use MySQLConnector.list_tables() "
            "+ MySQLConnector.describe_table() for schema introspection."
        )

    def profiling_queries(self) -> ProfilingQueryPack:
        return _PROFILING


DIALECTS["mysql"] = MysqlAdapter()
