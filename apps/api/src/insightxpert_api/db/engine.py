"""SQLAlchemy engine factory.

One process-wide engine, cached. On every new SQLite connection we set:
  - journal_mode=WAL      (concurrent readers + one writer)
  - synchronous=NORMAL    (durability-speed tradeoff; fine for our workload)
  - foreign_keys=ON       (SQLite default is OFF, which is a footgun)
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event

from ..config import get_settings

_engine: Engine | None = None


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        _engine = create_engine(url, future=True)
        if _engine.url.get_backend_name() == "sqlite":
            event.listen(_engine, "connect", _apply_sqlite_pragmas)
    return _engine


def reset_engine_cache() -> None:
    """Test hook only. Disposes the cached engine so the next call rebuilds."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
