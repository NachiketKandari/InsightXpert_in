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
    # Lazy import triggers registration.
    from . import sqlite as _sqlite  # noqa: F401

    # Postgres adapter registers itself when Task 9 lands; until then, only
    # sqlite is importable.
    try:
        from . import postgres as _postgres  # noqa: F401
    except ImportError:
        pass

    try:
        return DIALECTS[name]
    except KeyError as e:
        raise UnknownDialectError(
            f"unknown dialect: {name!r}; registered: {sorted(DIALECTS)}"
        ) from e
