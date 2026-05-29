"""Read-only database connector — dialect-dispatched.

The connector itself doesn't know SQL dialects; it calls into the adapter
registered for ``ref.dialect`` for connection-open, write-guard, teardown, and
timeout-exception classification.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Union

from .dialects import get_adapter
from .dialects.forbidden_sql import FORBIDDEN_SQL_RE
from .dialects.sqlite import FORBIDDEN_SQL_RE as _SQLITE_FORBIDDEN_SQL_RE

# Re-exported for callers that validate SQL before a connector is constructed
# (e.g. routes/automations.py). Now sourced from the canonical forbidden_sql module.
FORBIDDEN_SQL_RE = FORBIDDEN_SQL_RE

# Matches single-line (--…) and block (/* … */) SQL comments.
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    """Remove single-line and block comments from *sql*, returning the bare
    statement text so semicolons inside comments don't falsely trigger the
    multi-statement check."""
    return _COMMENT_RE.sub(" ", sql)


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
    """Per-request connector. Dispatches to the dialect adapter for all DB ops."""

    # DECISION(D-038): DatabaseRef as SimpleNamespace — backward compat for callers passing plain string paths
    # DECISION(D-064): SQL row limit (1000) and timeout (30s) — prevents OOM and hung queries
    def __init__(self, ref: Any, *, row_limit: int = 1000, timeout_s: int = 30) -> None:
        """``ref`` is a DatabaseRef (or a plain str path for backward compat)."""
        if isinstance(ref, str):
            import types
            ref = types.SimpleNamespace(local_path=ref, db_id="<inline>", dialect="sqlite")
        self._ref = ref
        self._adapter = get_adapter(ref.dialect)
        self._row_limit = row_limit
        self._timeout = timeout_s

    def execute(self, sql: str) -> QueryResult:
        # DECISION(D-053): Dual read-only enforcement — regex guard (here) + DB-level PRAGMA/session
        if self._adapter.forbidden_sql_re.search(sql):
            raise ForbiddenSQLError("write statements are not allowed")

        # Multi-statement check — strip single-line (--) and block (/* */)
        # comments, then reject if more than one statement remains.
        stripped = _strip_sql_comments(sql)
        if stripped.count(";") > 0:
            raise ForbiddenSQLError("multi-statement SQL is not allowed")

        start = time.perf_counter()
        con = self._adapter.open_readonly(self._ref)
        try:
            try:
                cursor = con.execute(sql)
            except Exception as e:
                if self._adapter.is_timeout_error(e):
                    raise SQLTimeoutError(str(e)) from e
                raise
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [list(r) for r in cursor.fetchmany(self._row_limit)]
            self._adapter.teardown_readonly(con)
        finally:
            con.close()

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return QueryResult(columns=columns, rows=rows, execution_time_ms=elapsed_ms)


# ---------------------------------------------------------------------------
# Unified connector dispatch (BYO-DB)
# ---------------------------------------------------------------------------
#
# Every code path that runs SQL against a user DB now goes through
# ``resolve_connector`` so callers don't bake in 'sqlite_file is the only
# backend' assumptions. ``DatabaseConnector`` (above) still owns the
# sqlite_file path; postgres dispatches to ``PostgresConnector``; libsql /
# sqlite_external are accepted as enum values but not yet wired (NotImplemented
# at dispatch time — Turso cutover plan handles those).


def resolve_connector(
    *,
    kind: str,
    config: Any | None = None,
    db_path: str | None = None,
) -> Union["DatabaseConnector", Any]:
    """Pick the right connector for a registry row.

    Args:
        kind: One of ``'sqlite_file'``, ``'postgres'``, ``'libsql'``,
            ``'sqlite_external'``.
        config: A typed connection config (e.g. ``PostgresConnection``) for
            non-sqlite_file kinds. Required for postgres / libsql.
        db_path: Local filesystem path for ``sqlite_file``.

    Raises:
        ValueError: unknown ``kind`` or missing required argument.
        NotImplementedError: ``libsql`` / ``sqlite_external`` are reserved
            but not yet wired (separate Turso plan).
    """
    if kind == "sqlite_file":
        if not db_path:
            raise ValueError("sqlite_file dispatch requires db_path")
        return DatabaseConnector(db_path)
    if kind == "postgres":
        # Local import — connections.postgres_connector pulls SQLAlchemy
        # engine code that we don't want to load on every sqlite-only path.
        from ..connections.postgres_connector import PostgresConnector
        from ..connections.types import PostgresConnection

        if not isinstance(config, PostgresConnection):
            raise ValueError("postgres dispatch requires a PostgresConnection config")
        # NOTE: Caller MUST call .dispose() on the returned connector when done.
        # PostgresConnector owns its own connection pool (pool_size=2).
        return PostgresConnector(config)
    if kind == "mysql":
        from ..connections.mysql_connector import MySQLConnector
        from ..connections.types import MySQLConnection

        if not isinstance(config, MySQLConnection):
            raise ValueError("mysql dispatch requires a MySQLConnection config")
        return MySQLConnector(config)
    if kind in ("libsql", "sqlite_external"):
        raise NotImplementedError(
            f"connector kind '{kind}' is reserved but not yet wired (Turso cutover plan)"
        )
    raise ValueError(f"unsupported db kind: {kind}")
