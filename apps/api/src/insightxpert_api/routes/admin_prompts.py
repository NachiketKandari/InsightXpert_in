"""/api/v1/admin/prompts — CRUD over prompt templates with .j2 fallback.

The resolver (``prompts.resolver.render_prompt``) is DB-first with file
fallback; these routes let an admin manage that DB layer. See
``prompts.admin_service`` for the unified list/detail semantics.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth.current_user import CurrentUser, require_admin
from ..prompts import admin_service

router = APIRouter(prefix="/api/v1/admin/prompts", tags=["admin-prompts"])


class PutPromptBody(BaseModel):
    content: str
    description: str | None = None


@router.get("/")
async def list_prompts(
    cu: CurrentUser = Depends(require_admin),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(admin_service.list_all)


@router.get("/{name}")
async def get_prompt(
    name: str,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    detail = await asyncio.to_thread(admin_service.get_detail, name)
    if detail is None:
        raise HTTPException(status_code=404, detail="not_found")
    return detail


@router.put("/{name}")
async def put_prompt(
    name: str,
    body: PutPromptBody,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    return await asyncio.to_thread(
        admin_service.upsert, name, body.content, body.description
    )


@router.delete("/{name}")
async def delete_prompt(
    name: str,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    existed = await asyncio.to_thread(admin_service.delete, name)
    if not existed:
        raise HTTPException(status_code=404, detail="not_found")
    return {"deleted": True}


@router.post("/{name}/reset")
async def reset_prompt(
    name: str,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    await asyncio.to_thread(admin_service.reset, name)
    return {"reset": True}
