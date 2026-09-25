"""Read-only Oracle query executor for BYO-DB connections.

Two layers of write protection (belt + suspenders):

1. ``FORBIDDEN_SQL_RE`` regex — fast pre-flight reject of obvious DDL/DML.
2. ``SET TRANSACTION READ ONLY`` issued best-effort on every connection before
   the user query runs, and the transaction is rolled back afterwards. Even if
   the regex misses something, Oracle rejects the write inside a read-only
   transaction. (Oracle has no Postgres-style session-level read-only flag, so
   this per-transaction statement is the closest equivalent.)

``oracledb`` runs in thin mode — no Instant Client needed.

Phase-1 limits (see PRD-oracle-db-support.md at the repo root):
* Only the ``service_name`` form is supported (covers PDBs, XE, Autonomous DB).
* Tables containing binary column types (BLOB/BFILE/RAW/LONG RAW) are rejected
  — see :data:`UNSUPPORTED_COLUMN_TYPES` and :func:`find_unsupported_columns`.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text

from ..db.dialects.forbidden_sql import FORBIDDEN_SQL_RE
from .types import OracleConnection

_FORBIDDEN_SQL = FORBIDDEN_SQL_RE

#: Binary / pointer column types with no faithful read path in Phase 1.
#: Compared against the base type (uppercased, parameter list stripped).
UNSUPPORTED_COLUMN_TYPES = frozenset({"BLOB", "BFILE", "RAW", "LONG RAW"})

#: Oracle-owned schemas that must never be introspected, even if requested.
SYSTEM_SCHEMAS = frozenset({
    "SYS", "SYSTEM", "DBSNMP", "OUTLN", "APPQOSSYS", "DBSFWUSER", "DVSYS",
    "AUDSYS", "GSMADMIN_INTERNAL", "XDB", "WMSYS", "CTXSYS", "MDSYS",
    "ORDSYS", "OLAPSYS", "EXFSYS", "SYSMAN", "OJVMSYS", "LBACSYS",
})

#: Cap on tables returned by discovery (parity with postgres/mysql: 200).
DISCOVERY_TABLE_LIMIT = 200


def is_system_schema(schema: str) -> bool:
    """True for Oracle-owned schemas (or APEX_* application schemas)."""
    upper = schema.strip().upper()
    return upper in SYSTEM_SCHEMAS or upper.startswith("APEX_")


def base_type(dtype: str) -> str:
    """Strip precision/qualifiers: ``'VARCHAR2(50)'`` → ``'VARCHAR2'``."""
    return dtype.strip().upper().split("(")[0].split(" ")[0]


def find_unsupported_columns(columns: list[dict[str, Any]]) -> list[str]:
    """Return ``['COL: TYPE', …]`` for columns with Phase-1-unsupported types."""
    return [
        f"{c['name']}: {c['type']}"
        for c in columns
        if base_type(str(c.get("type", ""))) in UNSUPPORTED_COLUMN_TYPES
    ]


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    execution_time_ms: int


@dataclass(frozen=True)
class TableDetails:
    name: str
    row_count: int | None
    column_count: int
    unsupported_columns: list[str]


class OracleConnector:
    def __init__(
        self,
        config: OracleConnection,
        *,
        row_limit: int = 1000,
        timeout_seconds: int = 30,
    ) -> None:
        self._config = config
        self._row_limit = row_limit
        self._timeout_seconds = timeout_seconds
        self._selected = (
            {t.lower() for t in config.selected_tables}
            if config.selected_tables
            else None
        )
        try:
            import oracledb  # driver must exist for either path
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "oracle support is not installed (missing 'oracledb' package)"
            ) from e
        if config.uses_descriptor():
            # Full TNS descriptors cannot be expressed as a SQLAlchemy URL
            # (the dialect would treat the blob as a TNS alias), so connect
            # through a creator callable instead. Pooling still applies.
            dsn = config.direct_dsn()
            user, password = config.username, config.password
            self._engine = create_engine(
                "oracle+oracledb://",
                creator=lambda: oracledb.connect(
                    user=user, password=password, dsn=dsn
                ),
                pool_size=2,
                max_overflow=0,
                pool_pre_ping=True,
            )
        else:
            self._engine = create_engine(
                config.to_dsn(),
                pool_size=2,
                max_overflow=0,
                pool_pre_ping=True,
            )

    # -- query ----------------------------------------------------------

    def execute(self, sql: str) -> QueryResult:
        if _FORBIDDEN_SQL.search(sql):
            raise ValueError("read-only: write/DDL statements not allowed")
        self._check_table_scope(sql)
        start = time.monotonic()
        with self._engine.connect() as conn:
            self._begin_read_only(conn)
            try:
                cur = conn.execute(text(sql))
                rows = cur.fetchmany(self._row_limit)
                columns = list(cur.keys())
            finally:
                conn.rollback()
        return QueryResult(
            columns=columns,
            rows=[tuple(r) for r in rows],
            execution_time_ms=int((time.monotonic() - start) * 1000),
        )

    def _check_table_scope(self, sql: str) -> None:
        """Enforce the picker's table allowlist, if one was saved."""
        if self._selected is None:
            return
        from ..vendored.agents_core.sql_guard import validate_tables

        error = validate_tables(sql, self._selected)
        if error:
            raise ValueError(error)

    @staticmethod
    def _begin_read_only(conn: Any) -> None:
        """Best-effort ``SET TRANSACTION READ ONLY`` before the user query."""
        # Permissions / driver quirks must not break reads — the regex
        # guard above remains in force.
        with contextlib.suppress(Exception):
            conn.execute(text("SET TRANSACTION READ ONLY"))

    # -- introspection --------------------------------------------------

    def _schema(self) -> str:
        schema = self._config.effective_schema()
        if is_system_schema(schema):
            raise ValueError(f"refusing to introspect system schema {schema!r}")
        return schema

    def list_tables(self) -> list[str]:
        schema = self._schema()
        sql = (
            "SELECT table_name FROM all_tables "
            "WHERE owner = :schema "
            f"ORDER BY table_name FETCH FIRST {DISCOVERY_TABLE_LIMIT} ROWS ONLY"
        )
        with self._engine.connect() as conn:
            self._begin_read_only(conn)
            try:
                rows = conn.execute(text(sql), {"schema": schema}).fetchall()
            finally:
                conn.rollback()
        return [r[0] for r in rows]

    def describe_table(self, name: str) -> list[dict[str, Any]]:
        schema = self._schema()
        sql = (
            "SELECT column_name, data_type, nullable "
            "FROM all_tab_columns "
            "WHERE owner = :schema AND table_name = :name "
            "ORDER BY column_id"
        )
        with self._engine.connect() as conn:
            self._begin_read_only(conn)
            try:
                rows = conn.execute(
                    text(sql), {"schema": schema, "name": name.upper()}
                ).fetchall()
            finally:
                conn.rollback()
        return [
            {"name": r[0], "type": r[1], "nullable": r[2] == "Y"} for r in rows
        ]

    def row_count(self, name: str) -> int | None:
        """Exact ``COUNT(*)`` (never sampled). ``None`` on timeout/error."""
        schema = self._schema()
        quoted = f'"{schema}"."{name.upper()}"'
        try:
            with self._engine.connect() as conn:
                self._begin_read_only(conn)
                try:
                    row = conn.execute(
                        text(f"SELECT COUNT(*) FROM {quoted}")
                    ).fetchone()
                finally:
                    conn.rollback()
                return int(row[0]) if row else None
        except Exception:
            return None

    def discovery_details(self) -> list[TableDetails]:
        """One-shot discovery for the connect dialog's table picker.

        Lists tables, describes them all with a single metadata query, and
        attaches best-effort exact row counts. Raises ``ValueError`` on
        connection/auth failures so the route can map it to a 400.
        """
        schema = self._schema()
        tables = self.list_tables()
        columns_by_table: dict[str, list[dict[str, Any]]] = {t: [] for t in tables}
        if tables:
            placeholders = ", ".join(f":t{i}" for i in range(len(tables)))
            sql = (
                "SELECT table_name, column_name, data_type, nullable "
                "FROM all_tab_columns "
                f"WHERE owner = :schema AND table_name IN ({placeholders}) "
                "ORDER BY table_name, column_id"
            )
            params: dict[str, Any] = {"schema": schema}
            params.update({f"t{i}": t for i, t in enumerate(tables)})
            with self._engine.connect() as conn:
                self._begin_read_only(conn)
                try:
                    rows = conn.execute(text(sql), params).fetchall()
                finally:
                    conn.rollback()
            for tname, cname, dtype, nullable in rows:
                columns_by_table.setdefault(tname, []).append(
                    {"name": cname, "type": dtype, "nullable": nullable == "Y"}
                )
        details = []
        for t in tables:
            cols = columns_by_table.get(t, [])
            details.append(
                TableDetails(
                    name=t,
                    row_count=self.row_count(t),
                    column_count=len(cols),
                    unsupported_columns=find_unsupported_columns(cols),
                )
            )
        return details

    def dispose(self) -> None:
        """Close all connections in the pool. Safe to call multiple times."""
        self._engine.dispose()
