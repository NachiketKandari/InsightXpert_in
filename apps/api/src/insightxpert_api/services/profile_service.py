"""Profile cache: save/load ``DatabaseProfile`` JSON under a session-scoped key.

The cache is keyed by ``(session_id, db_id)`` so uploaded DBs keep their profiles
isolated per user. Bundled DBs share the same keyspace but their profiles are
effectively per-session (v1 doesn't share profiles across sessions — cheap).
"""

from __future__ import annotations

from ..storage import ObjectStore
from ..vendored.pipeline_core.models.profile import DatabaseProfile


class ProfileService:
    """Thin wrapper over ``ObjectStore`` for ``DatabaseProfile`` persistence."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def key(self, session_id: str, db_id: str) -> str:
        return f"sessions/{session_id}/profiles/{db_id}/profile.json"

    def save(self, session_id: str, db_id: str, profile: DatabaseProfile) -> None:
        self._store.put_bytes(
            self.key(session_id, db_id),
            profile.model_dump_json(indent=2).encode("utf-8"),
        )

    def load(self, session_id: str, db_id: str) -> DatabaseProfile | None:
        k = self.key(session_id, db_id)
        if not self._store.exists(k):
            return None
        return DatabaseProfile.model_validate_json(self._store.get_bytes(k))

    def exists(self, session_id: str, db_id: str) -> bool:
        return self._store.exists(self.key(session_id, db_id))
