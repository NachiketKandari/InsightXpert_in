"""Oracle dialect adapter.

Read-only enforcement via ``SET TRANSACTION READ ONLY`` (best-effort,
per-connection) plus the canonical regex write-guard as belt-and-suspenders.
Oracle has no Postgres-style session-level read-only flag, so the adapter
issues the statement right after connecting and rolls back on teardown.

Thin mode (``oracledb``) — no Instant Client needed. ``oracledb`` is imported
lazily inside :meth:`OracleAdapter.open_readonly` so merely registering this
module never fails on hosts without the driver installed.

Profiling uses ``FETCH FIRST n ROWS ONLY`` (12c+) and ``DBMS_RANDOM.VALUE``
— there is no TABLESAMPLE in Oracle.
"""

from __future__ import annotations

import contextlib
from typing import Any

from . import DIALECTS
from .base import ProfilingQueryPack
from .forbidden_sql import FORBIDDEN_SQL_RE

_PROFILING = ProfilingQueryPack(
    null_count=(
        'SELECT COUNT(*) FROM "{schema}"."{table}" WHERE "{col}" IS NULL'
    ),
    distinct_count='SELECT COUNT(DISTINCT "{col}") FROM "{schema}"."{table}"',
    min_max='SELECT MIN("{col}"), MAX("{col}") FROM "{schema}"."{table}"',
    sample_rows=(
        'SELECT "{col}" FROM "{schema}"."{table}" '
        "ORDER BY DBMS_RANDOM.VALUE FETCH FIRST 100 ROWS ONLY"
    ),
)


class OracleAdapter:
    name = "oracle"
    sqlglot_dialect = "oracle"
    prompt_variant = "oracle"
    forbidden_sql_re = FORBIDDEN_SQL_RE

    def open_readonly(self, ref: Any) -> Any:
        import oracledb

        from .oracle_url import split_oracle_url

        url = getattr(ref, "connection_url", None)
        if not url:
            raise ValueError(f"Oracle ref {ref.db_id!r} missing connection_url")
        try:
            user, password, dsn = split_oracle_url(url)
        except ValueError as e:
            raise ValueError(f"Oracle ref {ref.db_id!r} has an unparsable connection URL") from e
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        with contextlib.suppress(Exception):
            conn.call_timeout = 30_000
        # Permissions / driver quirks must not break reads — the regex
        # guard in DatabaseConnector remains in force.
        with contextlib.suppress(Exception), conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
        return conn

    def teardown_readonly(self, conn: Any) -> None:
        """Roll back the read-only transaction. No-op on failure."""
        with contextlib.suppress(Exception):
            conn.rollback()

    def is_timeout_error(self, exc: BaseException) -> bool:
        msg = str(exc).lower()
        return (
            "01013" in msg  # ORA-01013: user requested cancel (call_timeout)
            or "timeout" in msg
            or "timed out" in msg
        )

    def open_database(self, ref: Any) -> Any:
        """Return a vendored-ABC Database wrapping a read-only connection."""
        from .oracle_database import OracleDatabase
        return OracleDatabase(ref)

    def extract_schema(self, db: Any, ref: Any) -> Any:
        """Extract a DatabaseSchema, honouring the saved table allowlist."""
        from .oracle_database import OracleDatabase
        from .oracle_schema import extract_oracle_schema

        if not isinstance(db, OracleDatabase):
            raise TypeError(
                "OracleAdapter.extract_schema expects an OracleDatabase; "
                f"got {type(db).__name__} — use open_database(ref) to build one."
            )
        selected = list(getattr(ref, "selected_tables", None) or [])
        return extract_oracle_schema(
            db.conn, owner=db.owner, selected_tables=selected or None
        )

    def profiling_queries(self) -> ProfilingQueryPack:
        return _PROFILING


DIALECTS["oracle"] = OracleAdapter()
