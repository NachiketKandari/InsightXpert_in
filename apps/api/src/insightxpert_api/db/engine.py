"""SQLAlchemy engine factory.

Two named engines:
  * request engine — served by `get_request_engine()` (also `get_engine()`,
    backwards-compatible alias). Used by every HTTP route handler.
  * background engine — served by `get_background_engine()`. Used only by
    the automations scheduler / runner. A small dedicated pool means
    background work cannot starve the request path.

On every new SQLite connection we set:
  - journal_mode=WAL      (concurrent readers + one writer)
  - synchronous=NORMAL    (durability-speed tradeoff; fine for our workload)
  - foreign_keys=ON       (SQLite default is OFF, which is a footgun)

For Postgres URLs we configure for transaction-mode pgbouncer:
  - pool_pre_ping=False   (pooler hands out warm conns)
  - prepare_threshold=None via connect_args (server-side prepared
    statements are incompatible with pgbouncer transaction mode)
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event

from ..config import get_settings

_request_engine: Engine | None = None
_background_engine: Engine | None = None


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _apply_statement_timeout(dbapi_connection, _connection_record) -> None:
    """Set per-connection statement_timeout for Postgres."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET statement_timeout = '30s'")
    finally:
        cursor.close()


def _build_engine(*, pool_size: int, max_overflow: int, pool_timeout: int) -> Engine:
    settings = get_settings()
    url = settings.database_url
    backend = url.split("://")[0].split("+")[0] if "://" in url else "sqlite"
    if backend == "sqlite":
        engine = create_engine(url, future=True)
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        return engine

    # `prepare_threshold` is a psycopg3-only connect kwarg. Setting it to
    # None disables server-side prepared statements, which is required for
    # pgbouncer transaction-mode pooling. Only pass it when the URL
    # explicitly selects the psycopg3 driver — psycopg2 and other drivers
    # would reject the kwarg.
    driver = url.split("://")[0]
    connect_args: dict[str, object] = {}
    if "+psycopg" in driver and "+psycopg2" not in driver:
        connect_args["prepare_threshold"] = None
        connect_args["connect_timeout"] = settings.db_connect_timeout

    engine = create_engine(
        url,
        future=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_recycle=settings.db_pool_recycle,
        connect_args=connect_args,
    )
    event.listen(engine, "connect", _apply_statement_timeout)
    return engine


def get_request_engine() -> Engine:
    global _request_engine
    if _request_engine is None:
        s = get_settings()
        _request_engine = _build_engine(
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout,
        )
    return _request_engine


def get_background_engine() -> Engine:
    global _background_engine
    if _background_engine is None:
        s = get_settings()
        _background_engine = _build_engine(
            pool_size=s.db_background_pool_size,
            max_overflow=s.db_background_max_overflow,
            pool_timeout=s.db_background_pool_timeout,
        )
    return _background_engine


def get_engine() -> Engine:
    """Backwards-compatible alias for the request-path engine.

    All existing callers keep working; only the scheduler/runner explicitly
    switches to ``get_background_engine()``.
    """
    return get_request_engine()


def reset_engine_cache() -> None:
    """Test hook only. Disposes both cached engines so the next call rebuilds."""
    global _request_engine, _background_engine
    if _request_engine is not None:
        _request_engine.dispose()
        _request_engine = None
    if _background_engine is not None:
        _background_engine.dispose()
        _background_engine = None
