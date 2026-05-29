"""Profile defaults route.

Returns the server-configured default profiling flags so the frontend can
show a simple "Run Profile" button for non-admin users (using the
configured defaults) while admins still see the full checkbox UI.

Authenticated — any logged-in user can read the defaults.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..auth.current_user import CurrentUser, get_current_user
from ..config import Settings, get_settings

router = APIRouter(prefix="/api/v1/profile-defaults", tags=["profile-defaults"])


@router.get("")
async def get_profile_defaults(
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    try:
        flags = json.loads(settings.profile_default_flags)
    except (json.JSONDecodeError, TypeError):
        flags = {}
    return {"flags": flags, "is_admin": cu.role == "admin"}
