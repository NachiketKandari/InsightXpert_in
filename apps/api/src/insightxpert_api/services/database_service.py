"""Database registry + resolver.

Combines two sources of SQLite DBs the user can query:
    • **bundled** — read-only samples shipped with the Cloud Run image
      (``./Databases/_shared/``).  The ``_shared/`` subdirectory is the
      canonical location as of Phase 1.3.  A one-release fallback also
      checks ``./Databases/{id}.sqlite`` so existing dev setups keep
      working until the operator re-runs ``scripts/fetch-bundled-dbs.sh``.
    • **uploaded** — per-session files the user posted to ``/databases/upload``; lives in the
      object store under ``sessions/<session_id>/dbs/<db_id>.sqlite``.

For uploaded DBs the service ``hydrates`` the blob to a local temp path on demand, since
``sqlite3`` can only read from a local filesystem path.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logging import get_logger
from ..storage import ObjectStore

_log = get_logger("database_service")


@dataclass(frozen=True)
class DatabaseRef:
    """Resolved database, ready for adapter.open_readonly()."""

    db_id: str
    source: str  # "bundled" | "uploaded"
    local_path: str | None = None  # None for Postgres-backed DBs
    dialect: str = "sqlite"
    connection_url: str | None = None
    connection_url_env_var: str | None = None

    def __repr__(self) -> str:
        url = self.connection_url
        if url:
            scheme_end = url.find("://")
            if scheme_end != -1:
                url = url[: scheme_end + 3] + "***"
            else:
                url = "***"
        return (
            f"DatabaseRef(db_id={self.db_id!r}, source={self.source!r}, "
            f"dialect={self.dialect!r}, connection_url={url})"
        )


class _LazyDatabaseRef:
    """A DatabaseRef whose ``local_path`` is hydrated from the object store on first access.

    This avoids the eager-download problem: :meth:`DatabaseService._list_uploaded`
    previously called ``_hydrate`` (which downloads from GCS) for *every* uploaded
    DB on every ``resolve()`` / ``list()`` call.  Now the download only fires when
    ``local_path`` is actually read — i.e. when someone needs to open the SQLite
    file.
    """

    dialect = "sqlite"

    def __init__(self, db_id: str, source: str, key: str, store: object) -> None:
        self.db_id = db_id
        self.source = source
        self._key = key
        self._store = store
        self._path: str | None = None

    @property
    def local_path(self) -> str:
        if self._path is None:
            self._path = self._hydrate(self._key)
        return self._path

    def _hydrate(self, key: str) -> str:
        """Materialize an object-store blob to a local tmp path."""
        tmp = Path(tempfile.gettempdir()) / "ix_uploads" / key
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if not tmp.exists():
            tmp.write_bytes(self._store.get_bytes(key))
        return str(tmp)

    def __hash__(self) -> int:
        return hash((self.db_id, self.source))


class DatabaseService:
    _BUNDLED = "bundled"
    _UPLOADED = "uploaded"

    def __init__(self, bundled_dir: str, store: ObjectStore) -> None:
        self._bundled_dir = Path(bundled_dir)
        self._store = store

    # ---- Listing ----------------------------------------------------------

    def list(self, session_id: str) -> list[DatabaseRef]:
        """Return all DBs visible to this session: bundled first, then uploaded."""
        return [*self._list_bundled(), *self._list_uploaded(session_id)]

    def _list_bundled(self) -> list[DatabaseRef]:
        """List bundled SQLite files.

        Primary location: ``<bundled_dir>/_shared/*.sqlite`` (Phase 1.3+).
        Fallback (one-release compat shim): ``<bundled_dir>/*.sqlite`` for any
        file not found under ``_shared/``.  Operators still on the old flat
        layout will see an INFO log telling them to re-run
        ``scripts/fetch-bundled-dbs.sh``.
        """
        if not self._bundled_dir.exists():
            return []

        shared_dir = self._bundled_dir / "_shared"
        seen: dict[str, Path] = {}

        # Primary: _shared/ subdirectory.
        if shared_dir.exists():
            for path in sorted(shared_dir.glob("*.sqlite")):
                seen[path.stem] = path

        # Fallback: flat Databases/ layout (pre-1.3 dev setups).
        for path in sorted(self._bundled_dir.glob("*.sqlite")):
            if path.stem not in seen:
                _log.info(
                    "bundled_db_flat_fallback",
                    db_id=path.stem,
                    path=str(path),
                    hint="Move this file to Databases/_shared/ by re-running scripts/fetch-bundled-dbs.sh",
                )
                seen[path.stem] = path

        sqlite_refs = [
            DatabaseRef(
                db_id=stem,
                source=self._BUNDLED,
                local_path=str(path.resolve()),
                dialect="sqlite",
            )
            for stem, path in sorted(seen.items())
        ]
        # Union in non-sqlite rows from the `databases` table. If both sources
        # list the same db_id, the SQLite file wins (shouldn't happen in practice).
        seen_ids = {r.db_id for r in sqlite_refs}
        pg_refs = [r for r in self._build_non_sqlite_refs() if r.db_id not in seen_ids]
        return sqlite_refs + pg_refs

    def _fetch_non_sqlite_rows(self) -> list[dict]:
        """Query the `databases` table for non-sqlite rows. Overrideable in tests.

        Returns an empty list if the app DB isn't reachable or the `databases`
        table doesn't exist (e.g. in unit tests that build a DatabaseService
        without running migrations). That keeps unrelated tests insulated from
        the cross-table dependency introduced by the postgres dialect seed row.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        from ..db.engine import get_engine

        try:
            engine = get_engine()
            with engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT db_id, kind, connection_config_encrypted "
                            "FROM databases WHERE kind IN ('postgres', 'libsql', 'sqlite_external', 'mysql')"
                        )
                    )
                    .mappings()
                    .all()
                )
            return [dict(r) for r in rows]
        except (OperationalError, ProgrammingError) as e:
            _log.debug("non_sqlite_rows_query_skipped", reason=str(e))
            return []

    def _build_non_sqlite_refs(self) -> list[DatabaseRef]:
        """Resolve each non-sqlite `databases` row into a DatabaseRef.

        Handles user-created BYO-DB connections (``connection_config_encrypted``).
        Rows whose config can't be decrypted are logged and skipped so one broken
        row doesn't hide the rest.
        """
        import json as _json

        from ..connections.encryption import decrypt
        from ..connections.types import MySQLConnection, PostgresConnection

        refs: list[DatabaseRef] = []
        for row in self._fetch_non_sqlite_rows():
            db_id_val = row["db_id"]
            kind_val = row["kind"]
            encrypted = row.get("connection_config_encrypted")

            if not encrypted:
                _log.warning(
                    "non_sqlite_db_no_encrypted_config",
                    db_id=db_id_val,
                )
                continue

            try:
                cfg_dict = _json.loads(decrypt(encrypted))
                if kind_val == "postgres":
                    cfg = PostgresConnection(**cfg_dict)
                    url = cfg.to_dsn()
                elif kind_val == "mysql":
                    cfg = MySQLConnection(**cfg_dict)
                    url = cfg.to_dsn()
                else:
                    _log.warning(
                        "non_sqlite_db_unknown_kind",
                        db_id=db_id_val,
                        kind=kind_val,
                    )
                    continue
            except Exception as exc:
                _log.warning(
                    "non_sqlite_db_decrypt_failed",
                    db_id=db_id_val,
                    error=str(exc),
                )
                continue

            refs.append(
                DatabaseRef(
                    db_id=db_id_val,
                    source=kind_val,
                    local_path=None,
                    dialect=kind_val,
                    connection_url=url,
                )
            )
        return refs

    def _list_uploaded(self, session_id: str) -> list[DatabaseRef]:
        """List uploaded DB keys, deferring hydration until local_path is accessed.

        Previously every call to _list_uploaded (which fires on both list() and
        resolve()) would eagerly download every uploaded SQLite file from the
        object store via _hydrate().  For GCS-backed deployments this meant a
        network download of every DB the user had ever uploaded, on every
        request — even requests that only needed one DB's path.

        Now we wrap the lazy-hydration logic in a property so the download only
        happens when local_path is actually read (i.e. when someone calls
        sqlite3.connect).  resolve() and list() no longer trigger downloads.
        """
        prefix = self._uploaded_prefix(session_id)
        refs: list[DatabaseRef] = []
        for key in self._store.list(prefix):
            if not key.endswith(".sqlite"):
                continue
            db_id = Path(key).stem
            refs.append(
                _LazyDatabaseRef(
                    db_id=db_id,
                    source=self._UPLOADED,
                    key=key,
                    store=self._store,
                )
            )
        return refs

    # ---- Resolution -------------------------------------------------------

    def resolve(self, session_id: str, db_id: str) -> DatabaseRef | None:
        for ref in self.list(session_id):
            if ref.db_id == db_id:
                return ref
        return None

    def resolve_connector(self, session_id: str, db_id: str) -> Any:
        """Return a ready-to-use connector for ``db_id``.

        Consults the ``databases`` registry for ``kind`` first:

            * ``sqlite_file`` (default for bundled / uploaded) → falls back to
              filesystem resolution via :meth:`resolve` and returns a
              :class:`DatabaseConnector`.
            * ``postgres`` → decrypts ``connection_config_encrypted``, builds a
              :class:`PostgresConnection`, returns a
              :class:`PostgresConnector`.
            * ``libsql`` / ``sqlite_external`` → reserved for the Turso plan;
              raises ``NotImplementedError`` at dispatch time.

        Returns ``None`` if ``db_id`` cannot be resolved at all.
        """
        from ..databases import repository as databases_repo
        from ..db.connector import resolve_connector as _resolve

        row = databases_repo.get_with_config(db_id)
        kind = (row or {}).get("kind") or "sqlite_file"

        if kind == "sqlite_file":
            ref = self.resolve(session_id, db_id)
            if ref is None:
                return None
            return _resolve(kind="sqlite_file", db_path=ref.local_path)

        if kind == "postgres":
            from ..connections.encryption import decrypt
            from ..connections.types import PostgresConnection
            import json as _json

            encrypted = (row or {}).get("connection_config_encrypted")
            if not encrypted:
                return None
            cfg = PostgresConnection(**_json.loads(decrypt(encrypted)))
            return _resolve(kind="postgres", config=cfg)

        if kind == "mysql":
            from ..connections.encryption import decrypt
            from ..connections.types import MySQLConnection
            import json as _json

            encrypted = (row or {}).get("connection_config_encrypted")
            if not encrypted:
                return None
            cfg = MySQLConnection(**_json.loads(decrypt(encrypted)))
            return _resolve(kind="mysql", config=cfg)

        # libsql / sqlite_external — surface the NotImplemented from the
        # central dispatch so the error message is consistent.
        return _resolve(kind=kind)

    # ---- Upload -----------------------------------------------------------

    def save_upload(self, session_id: str, db_id: str, data: bytes) -> DatabaseRef:
        """Store an uploaded SQLite file and return the resolved ref."""
        key = f"{self._uploaded_prefix(session_id)}{db_id}.sqlite"
        self._store.put_bytes(key, data)
        return DatabaseRef(db_id=db_id, source=self._UPLOADED, local_path=self._hydrate(key))

    # ---- Internals --------------------------------------------------------

    @staticmethod
    def _uploaded_prefix(session_id: str) -> str:
        return f"sessions/{session_id}/dbs/"

    def _hydrate(self, key: str) -> str:
        """Materialize an object-store blob to a local tmp path so sqlite3 can open it."""
        tmp = Path(tempfile.gettempdir()) / "ix_uploads" / key
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if not tmp.exists():
            tmp.write_bytes(self._store.get_bytes(key))
        return str(tmp)
