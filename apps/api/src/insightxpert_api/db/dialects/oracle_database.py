"""Database interface implementation for Oracle.

Satisfies the vendored ``Database`` ABC (execute + close + context manager) so
the profiler can treat Oracle DBs the same as SQLite/Postgres ones.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ...vendored.pipeline_core.db import Database
from .oracle_url import split_oracle_url


class OracleDatabase(Database):
    """Vendored-Database wrapper around a read-only oracledb connection."""

    def __init__(self, ref: Any) -> None:
        import oracledb

        url = getattr(ref, "connection_url", None)
        if not url:
            raise ValueError(f"Oracle ref {ref.db_id!r} missing connection_url")
        try:
            user, password, dsn = split_oracle_url(url)
        except ValueError as e:
            raise ValueError(
                f"Oracle ref {ref.db_id!r} has an unparsable connection URL"
            ) from e
        self.db_id = ref.db_id
        self.owner = self._owner_for(ref, user)
        self._conn = oracledb.connect(user=user, password=password, dsn=dsn)
        with contextlib.suppress(Exception):
            self._conn.call_timeout = 120_000
        with contextlib.suppress(Exception), self._conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")

    @staticmethod
    def _owner_for(ref: Any, user: str) -> str:
        """Schema owner to introspect: explicit ref owner or the login user."""
        owner = getattr(ref, "owner", None) or getattr(ref, "schema", None) or ""
        return (owner.strip().upper() if owner else user.strip().upper())

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params or None)
            if cur.description is None:
                return []
            return list(cur.fetchall())

    @property
    def conn(self) -> Any:
        """Underlying oracledb connection for callers that need cursor access
        (e.g. the Oracle schema extractor). Kept read-only at the protocol
        level — mutating the connection here breaks the ``Database`` ABC's
        abstraction."""
        return self._conn

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.rollback()
        self._conn.close()
