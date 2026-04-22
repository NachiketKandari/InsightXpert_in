"""DialectAdapter protocol — the contract every dialect implements."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class UnknownDialectError(Exception):
    """Raised when get_adapter() is called with an unregistered dialect name."""


@dataclass(frozen=True)
class ProfilingQueryPack:
    """SQL templates used by the profiling runner.

    Placeholders: ``{schema}``, ``{table}``, ``{col}``. Implementors MUST
    quote identifiers via dialect-specific helpers (e.g. ``psycopg.sql.Identifier``)
    at render time. The templates here are strings, not SQL objects.
    """
    null_count: str
    distinct_count: str
    min_max: str
    sample_rows: str


@runtime_checkable
class DialectAdapter(Protocol):
    """Contract for a query-target dialect.

    Two rules:
    1. Call sites never branch on dialect; they call the methods here.
    2. Implementors never edit the vendored pipeline_core tree.
    """

    name: str
    sqlglot_dialect: str
    prompt_variant: str
    forbidden_sql_re: re.Pattern[str]

    def open_readonly(self, ref: Any) -> Any: ...
    def teardown_readonly(self, conn: Any) -> None: ...
    def is_timeout_error(self, exc: BaseException) -> bool: ...
    # Vendored-Database ABC instance for stages that want a uniform
    # ``with db:`` / ``db.execute(sql)`` shape (notably the profiling runner).
    # Distinct from ``open_readonly`` which returns a raw DB-API 2 connection.
    def open_database(self, ref: Any) -> Any: ...
    def extract_schema(self, db: Any, ref: Any) -> Any: ...
    def profiling_queries(self) -> ProfilingQueryPack: ...
