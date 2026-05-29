"""Dialect adapter registry.

Each dialect (sqlite, postgres, ...) registers a `DialectAdapter` here.
Call sites resolve via `get_adapter(name)` and never touch a dialect-specific
module directly.
"""
from __future__ import annotations

from .base import DialectAdapter, ProfilingQueryPack, UnknownDialectError

__all__ = [
    "DialectAdapter",
    "ProfilingQueryPack",
    "UnknownDialectError",
    "get_adapter",
    "DIALECTS",
]

# Registry is populated by the per-dialect modules at import time.
DIALECTS: dict[str, DialectAdapter] = {}


def get_adapter(name: str) -> DialectAdapter:
    """Resolve a dialect name to its adapter. Raises UnknownDialectError."""
    # Lazy imports trigger self-registration via side-effect at module load.
    # Both psycopg and sqlite3 are declared deps — if an import fails here, it
    # IS a misconfiguration and we want it loud, not swallowed.
    from . import mysql as _mysql  # noqa: F401
    from . import postgres as _postgres  # noqa: F401
    from . import sqlite as _sqlite  # noqa: F401

    try:
        return DIALECTS[name]
    except KeyError as e:
        raise UnknownDialectError(
            f"unknown dialect: {name!r}; registered: {sorted(DIALECTS)}"
        ) from e
