"""Database registry + resolver.

Combines two sources of SQLite DBs the user can query:
    • **bundled** — read-only samples shipped with the Cloud Run image (``./Databases/``).
    • **uploaded** — per-session files the user posted to ``/databases/upload``; lives in the
      object store under ``sessions/<session_id>/dbs/<db_id>.sqlite``.

For uploaded DBs the service ``hydrates`` the blob to a local temp path on demand, since
``sqlite3`` can only read from a local filesystem path.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..storage import ObjectStore


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
        if not self._bundled_dir.exists():
            return []
        refs: list[DatabaseRef] = []
        for path in sorted(self._bundled_dir.glob("*.sqlite")):
            refs.append(
                DatabaseRef(
                    db_id=path.stem,
                    source=self._BUNDLED,
                    local_path=str(path.resolve()),
                )
            )
        return refs

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
