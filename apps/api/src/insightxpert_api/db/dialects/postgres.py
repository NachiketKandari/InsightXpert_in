"""PostgreSQL dialect adapter.

Read-only enforcement via ``default_transaction_read_only=on`` at session
scope, plus a regex write-guard as belt-and-suspenders. Statement timeout
and idle-in-transaction timeout set at connection open.
"""
from __future__ import annotations

import re
from typing import Any

import psycopg

from . import DIALECTS
from .base import DialectAdapter, ProfilingQueryPack

# The regex intentionally excludes SQLite-only keywords (ATTACH / DETACH /
# PRAGMA) and adds Postgres-specific write forms (COPY ... FROM, GRANT / REVOKE,
# TRUNCATE). Placed as a module-level constant so routes that pre-validate SQL
# without constructing a connector can import it directly.
FORBIDDEN_SQL_RE = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|"
    r"GRANT|REVOKE|SECURITY\s+DEFINER"
    r")\b|"
    r"\bCOPY\b\s+\S+\s+\bFROM\b",
    re.IGNORECASE,
)

_PROFILING = ProfilingQueryPack(
    null_count=(
        'SELECT COUNT(*) FILTER (WHERE "{col}" IS NULL) '
        'FROM "{schema}"."{table}"'
    ),
    distinct_count='SELECT COUNT(DISTINCT "{col}") FROM "{schema}"."{table}"',
    min_max='SELECT MIN("{col}"), MAX("{col}") FROM "{schema}"."{table}"',
    sample_rows=(
        'SELECT "{col}" FROM "{schema}"."{table}" '
        'TABLESAMPLE SYSTEM (1) LIMIT 100'
    ),
)


class PostgresAdapter:
    name = "postgres"
    sqlglot_dialect = "postgres"
    prompt_variant = "postgres"
    forbidden_sql_re = FORBIDDEN_SQL_RE

    def open_readonly(self, ref: Any) -> psycopg.Connection:
        if not ref.connection_url:
            raise ValueError(f"Postgres ref {ref.db_id!r} missing connection_url")
        conn = psycopg.connect(
            ref.connection_url,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=30000 "
                "-c idle_in_transaction_session_timeout=10000"
            ),
            autocommit=True,
        )
        return conn

    def teardown_readonly(self, conn: psycopg.Connection) -> None:
        """No-op on Postgres — read-only is session-scoped, closes with the conn."""

    def is_timeout_error(self, exc: BaseException) -> bool:
        """Postgres surfaces statement_timeout via psycopg.errors.QueryCanceled."""
        return isinstance(exc, psycopg.errors.QueryCanceled)

    def extract_schema(self, conn: Any) -> Any:
        # Split into its own module to keep this file focused on the adapter contract.
        from .postgres_schema import extract_postgres_schema
        return extract_postgres_schema(conn)

    def profiling_queries(self) -> ProfilingQueryPack:
        return _PROFILING


DIALECTS["postgres"] = PostgresAdapter()
