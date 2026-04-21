"""DB visibility service.

Visibility states (enforced by ``databases_visibility_check``):
    * ``private`` — owner only.
    * ``shared``  — owner + users listed in ``database_shares``.
    * ``public``  — everyone.

Admins see all DBs regardless of visibility.

This module does not touch the filesystem. :class:`DatabaseService` still owns
the bundled / uploaded file registry; this layer answers "is `db_id` visible to
this user" and maintains the share list.
"""

from __future__ import annotations

from typing import Any

from . import repository


class DatabaseVisibilityError(Exception):
    """Base class for service errors."""


class InvalidVisibilityError(DatabaseVisibilityError):
    pass


_VALID = {"private", "shared", "public"}


def list_visible(user_id: str, is_admin: bool) -> list[dict[str, Any]]:
    return repository.list_visible(user_id, is_admin)


def list_all_admin() -> list[dict[str, Any]]:
    """Admin view: all DBs with owner email + share list joined in."""
    return repository.list_all_admin()


def create(
    db_id: str,
    owner_user_id: str | None,
    visibility: str = "private",
    size_bytes: int = 0,
) -> None:
    if visibility not in _VALID:
        raise InvalidVisibilityError(visibility)
    repository.insert_db(db_id, owner_user_id, visibility, size_bytes)


def upsert_private(db_id: str, owner_user_id: str, size_bytes: int) -> None:
    """Called from the upload route. Idempotent."""
    repository.upsert_private(db_id, owner_user_id, size_bytes)


def set_visibility(
    db_id: str, visibility: str, shared_with: list[str] | None = None
) -> None:
    if visibility not in _VALID:
        raise InvalidVisibilityError(visibility)
    repository.set_visibility(db_id, visibility, shared_with or [])


def visible_ids(user_id: str, is_admin: bool) -> set[str]:
    """Return the set of db_ids visible to this user. Convenience for filtering."""
    return {r["db_id"] for r in repository.list_visible(user_id, is_admin)}
