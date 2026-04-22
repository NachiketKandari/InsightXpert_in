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
        settings = get_settings()
        url = settings.database_url
        backend = url.split("://")[0].split("+")[0] if "://" in url else "sqlite"
        if backend == "sqlite":
            _engine = create_engine(url, future=True)
            event.listen(_engine, "connect", _apply_sqlite_pragmas)
        else:
            _engine = create_engine(
                url,
                future=True,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_pre_ping=settings.db_pool_pre_ping,
            )
    return _engine


def reset_engine_cache() -> None:
    """Test hook only. Disposes the cached engine so the next call rebuilds."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
