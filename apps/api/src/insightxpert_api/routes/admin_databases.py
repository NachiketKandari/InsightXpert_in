"""/api/v1/admin/databases — enriched admin-only DB list.

Complements the user-facing ``GET /api/v1/databases`` (which filters by
visibility) with a full view that joins owner email and share list.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.current_user import CurrentUser, require_admin
from ..databases import repository as databases_repo
from ..databases import service as visibility_service

router = APIRouter(prefix="/api/v1/admin/databases", tags=["admin-databases"])


@router.get("/")
async def list_all_databases(
    cu: CurrentUser = Depends(require_admin),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(visibility_service.list_all_admin)


class AdminDatabasePatch(BaseModel):
    """Tier-1 admin patch payload.

    Only ``pipeline_mode_default`` is writable today. ``null`` clears the
    override (row inherits system default ``"linked"``). Additional fields
    can land here as admin-editable DB metadata grows.
    """

    pipeline_mode_default: Literal["linked", "full_schema"] | None = None


@router.patch("/{db_id}")
async def patch_database(
    db_id: str,
    body: AdminDatabasePatch,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only: update per-DB metadata (currently ``pipeline_mode_default``)."""
    ok = await asyncio.to_thread(
        databases_repo.set_pipeline_mode_default, db_id, body.pipeline_mode_default
    )
    if not ok:
        raise HTTPException(status_code=404, detail="database_not_found")
    return {
        "db_id": db_id,
        "pipeline_mode_default": body.pipeline_mode_default,
    }
