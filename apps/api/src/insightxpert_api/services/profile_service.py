"""Profile cache: save/load ``DatabaseProfile`` to the metadata DB.

Backed by the ``database_profiles`` Postgres table (Phase 4b). Replaces the
previous object-store-blob persistence — profiles are now queryable, joinable,
and survive object-store rotation. Schema:
``(db_id, profile_kind)`` PK, with audit columns (``generated_at``,
``generated_by``, token + cost accounting).

The public API still takes ``session_id`` as the first arg for backwards
compatibility with every existing caller. In this codebase ``session_id``
is identical to the user id (sessions are 1:1 with users post-B1), so we
record it as ``owner_user_id`` / ``generated_by``.
"""

from __future__ import annotations

from ..profiling import repository as profiles_repo
from ..vendored.pipeline_core.models.profile import DatabaseProfile


class ProfileService:
    """Persists ``DatabaseProfile`` JSON to the ``database_profiles`` table."""

    def __init__(self, store=None) -> None:  # noqa: ARG002
        # `store` argument retained for backwards compatibility with the
        # earlier ObjectStore-backed implementation; ignored as of Phase 4b.
        # Drop the argument from callers when convenient.
        pass

    def save(
        self,
        session_id: str,
        db_id: str,
        profile: DatabaseProfile,
        *,
        profile_kind: str = "base",
    ) -> None:
        profiles_repo.upsert(
            db_id=db_id,
            profile_kind=profile_kind,
            owner_user_id=session_id,
            generated_by=session_id,
            profile_json=profile.model_dump_json(),
        )

    def load(
        self,
        session_id: str,  # noqa: ARG002 — kept for API compat; profile is per-db
        db_id: str,
        *,
        profile_kind: str = "base",
    ) -> DatabaseProfile | None:
        row = profiles_repo.get(db_id, profile_kind)
        if row is None:
            return None
        return DatabaseProfile.model_validate_json(row["profile_json"])

    def exists(
        self,
        session_id: str,  # noqa: ARG002 — kept for API compat
        db_id: str,
        *,
        profile_kind: str = "base",
    ) -> bool:
        return profiles_repo.exists(db_id, profile_kind)
