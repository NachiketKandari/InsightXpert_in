"""Auth dependencies — re-export surface."""

from __future__ import annotations

from .current_user import CurrentUser, get_current_user, require_admin

__all__ = ["CurrentUser", "get_current_user", "require_admin"]
