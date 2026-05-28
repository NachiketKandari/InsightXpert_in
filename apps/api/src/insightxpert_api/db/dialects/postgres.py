"""PostgreSQL dialect adapter.

Read-only enforcement via ``default_transaction_read_only=on`` at session
scope, plus a regex write-guard as belt-and-suspenders. Statement timeout
and idle-in-transaction timeout set at connection open.
"""
from __future__ import annotations

from typing import Any

import psycopg

from . import DIALECTS
from .base import DialectAdapter, ProfilingQueryPack
from .forbidden_sql import FORBIDDEN_SQL_RE

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
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )
        return conn

    def teardown_readonly(self, conn: psycopg.Connection) -> None:
        """No-op on Postgres — read-only is session-scoped, closes with the conn."""

    def is_timeout_error(self, exc: BaseException) -> bool:
        """Postgres surfaces statement_timeout via psycopg.errors.QueryCanceled."""
        return isinstance(exc, psycopg.errors.QueryCanceled)

    def open_database(self, ref: Any) -> Any:
        """Return a vendored-ABC Database wrapping a read-only psycopg connection."""
        from .postgres_database import PostgresDatabase
        return PostgresDatabase(ref)

    def extract_schema(self, db: Any, ref: Any) -> Any:
        """Extract a DatabaseSchema. ``db`` is a ``PostgresDatabase`` (vendored
        ABC); we reach into its underlying psycopg connection via ``db.conn``
        and delegate to ``extract_postgres_schema`` with the schema name
        derived from the ref.
        """
        from .postgres_database import PostgresDatabase
        from .postgres_schema import extract_postgres_schema

        if not isinstance(db, PostgresDatabase):
            raise TypeError(
                "PostgresAdapter.extract_schema expects a PostgresDatabase; "
                "got {} — use open_database(ref) to build one.".format(type(db).__name__)
            )
        return extract_postgres_schema(db.conn, schema_name=_pg_schema_for_ref(ref))

    def profiling_queries(self) -> ProfilingQueryPack:
        return _PROFILING


def _pg_schema_for_ref(ref: Any) -> str:
    """Derive the Postgres schema name from a DatabaseRef.

    Convention: a DB row with db_id ending in ``_pg`` puts its tables in the
    schema named by the prefix (e.g. ``toxicology_pg`` → ``toxicology``).
    Any other db_id falls back to ``public``. This keeps us moving without
    adding a column to the ``databases`` table; revisit when a second
    Postgres-backed DB arrives that doesn't fit the convention.
    """
    if ref.db_id.endswith("_pg"):
        return ref.db_id[: -len("_pg")]
    return "public"


DIALECTS["postgres"] = PostgresAdapter()
