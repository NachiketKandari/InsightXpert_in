"""Client-config route.

Returns the feature-flag map the FE reads on every page load to gate nav items
and feature surfaces. Intentionally unauthenticated — the FE hits this BEFORE
the password gate prompt renders.

Response shape mirrors the FE's ``ClientConfig`` / ``OrgConfig`` types so the
Zustand store can hydrate directly without a translation layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(prefix="/api/v1/client-config", tags=["client-config"])

_FEATURES: dict[str, bool] = {
    "sql_executor": True,
    "model_switching": False,  # admin-only by default; admins always get it
    "rag_training": False,
    "rag_retrieval": False,
    "chart_rendering": True,
    "conversation_export": False,
    "agent_process_sidebar": True,
    "clarification_enabled": True,
    "stats_context_injection": False,
}

_DEFAULTS = {
    "features": dict(_FEATURES),
    "branding": None,
}


@router.get("")
async def get_client_config(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "private, max-age=300"
    return {
        "config": {
            "org_id": "default",
            "org_name": "default",
            "features": dict(_FEATURES),
            "branding": None,
        },
        "is_admin": False,
        "org_id": None,
    }
