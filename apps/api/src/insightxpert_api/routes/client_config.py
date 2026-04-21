"""Client-config route.

Returns the static feature-flag map the forked FE reads on every page load to
gate nav items + feature surfaces. Intentionally unauthenticated: the FE hits
this BEFORE the password gate prompt renders.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/client-config", tags=["client-config"])


_FEATURES: dict[str, bool] = {
    "sql_runner": True,
    "upload": True,
    "profile_editor": False,
    "voice": False,
    "ollama": False,
    "automations": False,
    "admin": False,
    "insights": False,
    "notifications": False,
}


@router.get("")
async def get_client_config() -> dict[str, object]:
    return {"features": dict(_FEATURES), "version": "0.1.0"}
