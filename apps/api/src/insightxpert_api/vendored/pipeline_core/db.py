"""Database abstraction layer.

All raw database access goes through the Database interface. Only this module
imports sqlite3 — the rest of the codebase calls db.execute() and stays
unaware of the underlying engine.

Typical usage:
    with open_db("toxicology") as db:
        rows = db.execute('SELECT name FROM sqlite_master WHERE type="table"')
"""
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

from insightxpert_api.vendored.pipeline_core.config import settings


class Database(ABC):
    """Minimal read-oriented database interface."""

    #: Logical identifier for the database (e.g. "toxicology")
    db_id: str

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Run a SQL query and return all result rows as a list of tuples."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release the underlying connection."""
        ...

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_) -> None:
        self.close()


class SQLiteDatabase(Database):
    """Read-only SQLite connection backed by a single .sqlite file.

    Uses mode=ro to prevent accidental writes and check_same_thread=False so
    the same connection can be handed to a thread-pool executor (safe for reads).
    """

    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")
        self.db_id = db_path.stem
        self._conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            check_same_thread=False,
        )

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()


def open_db(db_id: str, benchmark: str = "bird_dev") -> Database:
    """Open a read-only Database for the given database ID.

    benchmark controls which backend is used:
      "bird_dev" (default) → SQLite: Databases/{db_id}.sqlite
      "mini_dev"           → SQLite: Test/mini_dev/minidev/MINIDEV/dev_databases/{db_id}/{db_id}.sqlite
      "spider_snow"        → Snowflake: connects using credentials from .env

    Raises FileNotFoundError (SQLite) or ImportError (Snowflake missing package).
    """
    if benchmark == "spider_snow":
        from insightxpert_api.vendored.pipeline_core.db_snowflake import SnowflakeDatabase
        cfg = settings.get_snowflake_config()
        cfg["database"] = db_id
        return SnowflakeDatabase(db_id=db_id, **cfg)
    return SQLiteDatabase(settings.get_db_path(db_id, benchmark))
