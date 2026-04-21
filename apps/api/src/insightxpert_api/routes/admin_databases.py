"""/api/v1/admin/databases — enriched admin-only DB list.

Complements the user-facing ``GET /api/v1/databases`` (which filters by
visibility) with a full view that joins owner email and share list.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from ..auth.current_user import CurrentUser, require_admin
from ..databases import service as visibility_service

router = APIRouter(prefix="/api/v1/admin/databases", tags=["admin-databases"])


@router.get("/")
async def list_all_databases(
    cu: CurrentUser = Depends(require_admin),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(visibility_service.list_all_admin)
