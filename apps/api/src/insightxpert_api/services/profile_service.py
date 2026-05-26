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

Reads go through a process-level cache (``ProfileCache``) — repeated loads
for the same ``(db_id, profile_kind)`` skip the DB round-trip. Writes
invalidate the cache before returning so the next read sees fresh bytes.

Profile editing: user overrides are stored in a separate ``profile_overrides``
table and applied to the base profile on every read. This keeps generated
data (the profile JSON) clean and allows reverting individual fields.
"""

from __future__ import annotations

import json

from ..profiling import repository as profiles_repo
from ..profiling.cache import get_process_profile_cache
from ..vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnQuirks,
    DatabaseProfile,
)


def _apply_field_override(
    col: ColumnProfile, field_path: str, value_json: str
) -> ColumnProfile:
    """Apply a single field override to a ColumnProfile, returning a copy."""
    value = json.loads(value_json)
    col_dict = col.model_dump()

    if "." in field_path:
        # Nested field: e.g. "quirks.semantic_hint" or "quirks.enum_labels"
        parent_key, child_key = field_path.split(".", 1)
        parent = col_dict.get(parent_key)
        if isinstance(parent, dict):
            if child_key in ("enum_labels",):
                parent[child_key] = value if isinstance(value, dict) else parent[child_key]
            else:
                parent[child_key] = value
        elif hasattr(parent, "model_copy"):
            if child_key in ("enum_labels",):
                setattr(parent, child_key, value if isinstance(value, dict) else getattr(parent, child_key))
            else:
                setattr(parent, child_key, value)
    else:
        col_dict[field_path] = value

    return ColumnProfile.model_validate(col_dict)


class ProfileService:
    """Persists ``DatabaseProfile`` JSON to the ``database_profiles`` table."""

    def __init__(self, store=None) -> None:  # noqa: ARG002
        # `store` argument retained for backwards compatibility with the
        # earlier ObjectStore-backed implementation; ignored as of Phase 4b.
        # Drop the argument from callers when convenient.
        self._cache = get_process_profile_cache()

    # --- base profile save/load -------------------------------------------

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
        self._cache.invalidate(db_id, profile_kind)

    def load(
        self,
        session_id: str,  # noqa: ARG002 — kept for API compat; profile is per-db
        db_id: str,
        *,
        profile_kind: str = "base",
    ) -> DatabaseProfile | None:
        base = self._load_base(db_id, profile_kind)
        if base is None:
            return None
        overrides = profiles_repo.get_overrides(db_id)
        if overrides:
            base = self._apply_overrides(base, overrides)
        return base

    def _load_base(
        self, db_id: str, profile_kind: str = "base"
    ) -> DatabaseProfile | None:
        def _loader(db_id_: str, kind_: str) -> DatabaseProfile | None:
            row = profiles_repo.get(db_id_, kind_)
            if row is None:
                return None
            return DatabaseProfile.model_validate_json(row["profile_json"])

        return self._cache.get(db_id, profile_kind, _loader)

    def exists(
        self,
        session_id: str,  # noqa: ARG002 — kept for API compat
        db_id: str,
        *,
        profile_kind: str = "base",
    ) -> bool:
        return self.load(session_id, db_id, profile_kind=profile_kind) is not None

    # --- join graph -------------------------------------------------------

    def save_join_graph(
        self,
        session_id: str,  # noqa: ARG002
        db_id: str,
        join_graph_json: str,
        *,
        profile_kind: str = "base",
    ) -> None:
        """Persist a join graph for a database profile.

        Join graphs are separate from the profile JSON so they can be loaded
        independently by the schema linker without deserializing the full profile.
        """
        profiles_repo.set_join_graph(db_id, join_graph_json, profile_kind)

    def load_join_graph(
        self,
        session_id: str,  # noqa: ARG002
        db_id: str,
        *,
        profile_kind: str = "base",
    ) -> str | None:
        """Load a join graph for a database profile, or None."""
        return profiles_repo.get_join_graph(db_id, profile_kind)

    # --- user hints -------------------------------------------------------

    def set_user_hints(
        self,
        session_id: str,  # noqa: ARG002
        db_id: str,
        user_hints: str,
        *,
        profile_kind: str = "base",
    ) -> None:
        """Persist pre-profiling domain hints for a database."""
        profiles_repo.set_user_hints(db_id, user_hints, profile_kind)

    def get_user_hints(
        self,
        session_id: str,  # noqa: ARG002
        db_id: str,
        *,
        profile_kind: str = "base",
    ) -> str | None:
        """Load pre-profiling domain hints for a database, or None."""
        return profiles_repo.get_user_hints(db_id, profile_kind)

    # --- profile overrides ------------------------------------------------

    def save_override(
        self,
        edited_by: str,
        db_id: str,
        table_name: str,
        column_name: str,
        field_path: str,
        value_json: str,
    ) -> None:
        """Persist a user override for a single column field."""
        profiles_repo.upsert_override(
            db_id=db_id,
            table_name=table_name,
            column_name=column_name,
            field_path=field_path,
            value_json=value_json,
            edited_by=edited_by,
        )
        self._cache.invalidate(db_id, "base")

    def delete_profile(self, db_id: str) -> int:
        """Delete all profile rows and overrides for a database. Returns total rowcount."""
        overrides_deleted = profiles_repo.delete_overrides_for_db(db_id)
        profiles_deleted = profiles_repo.delete_for_db(db_id)
        self._cache.invalidate(db_id, "base")
        return overrides_deleted + profiles_deleted

    def delete_override(
        self,
        db_id: str,
        table_name: str,
        column_name: str,
        field_path: str,
    ) -> int:
        """Delete a single field override. Returns rowcount."""
        count = profiles_repo.delete_override(
            db_id, table_name, column_name, field_path
        )
        if count:
            self._cache.invalidate(db_id, "base")
        return count

    def get_overrides(self, db_id: str) -> list[dict]:
        """Return all overrides for a database profile."""
        return profiles_repo.get_overrides(db_id)

    @staticmethod
    def _apply_overrides(
        profile: DatabaseProfile, overrides: list[dict]
    ) -> DatabaseProfile:
        """Apply user overrides to a DatabaseProfile, returning a new copy."""
        # Build index: (table_name, column_name) -> list of (field_path, value_json)
        by_column: dict[tuple[str, str], list[dict]] = {}
        for ov in overrides:
            key = (ov["table_name"], ov["column_name"])
            by_column.setdefault(key, []).append(ov)

        tables = list(profile.tables)
        for ti, table in enumerate(tables):
            columns = list(table.columns)
            for ci, col in enumerate(columns):
                ovs = by_column.get((table.name, col.name))
                if ovs:
                    for ov in ovs:
                        col = _apply_field_override(col, ov["field_path"], ov["value_json"])
                    columns[ci] = col
            tables[ti] = table.model_copy(update={"columns": columns})

        return profile.model_copy(update={"tables": tables})
