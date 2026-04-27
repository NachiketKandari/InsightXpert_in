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

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..logging import get_logger
from ..storage import ObjectStore

_log = get_logger("database_service")


@dataclass(frozen=True)
class DatabaseRef:
    """Resolved database, ready for ``sqlite3.connect(local_path)``."""

    db_id: str
    source: str  # "bundled" | "uploaded"
    local_path: str


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

        return [
            DatabaseRef(
                db_id=stem,
                source=self._BUNDLED,
                local_path=str(path.resolve()),
            )
            for stem, path in sorted(seen.items())
        ]

    def _list_uploaded(self, session_id: str) -> list[DatabaseRef]:
        prefix = self._uploaded_prefix(session_id)
        refs: list[DatabaseRef] = []
        for key in self._store.list(prefix):
            if not key.endswith(".sqlite"):
                continue
            db_id = Path(key).stem
            refs.append(
                DatabaseRef(
                    db_id=db_id,
                    source=self._UPLOADED,
                    local_path=self._hydrate(key),
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

        row = databases_repo.get(db_id)
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
