"""Auth dependencies. `require_session` is kept as a one-commit alias so the
B1 route swap (Task 14) is mechanical; it will be removed in Task 15.
"""

from __future__ import annotations

from .current_user import CurrentUser, get_current_user, require_admin

# One-commit alias during the swap; removed in Task 15.
require_session = get_current_user

__all__ = ["CurrentUser", "get_current_user", "require_admin", "require_session"]
