"""Notifications list/stream/mark-read endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from ..auth.current_user import CurrentUser, get_current_user
from ..automations import notifications as notif_module
from ..automations.service import NotificationService

log = logging.getLogger("insightxpert_api.routes.notifications")

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _svc() -> NotificationService:
    return NotificationService()


@router.get("")
async def list_notifications(
    user: CurrentUser = Depends(get_current_user),
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
):
    return await asyncio.to_thread(
        _svc().list_for_user, user.id, unread_only=unread, limit=limit
    )


@router.get("/count")
async def notification_count(user: CurrentUser = Depends(get_current_user)):
    count = await asyncio.to_thread(_svc().unread_count, user.id)
    return {"count": count}


@router.get("/stream")
async def stream_notifications(
    request: Request, user: CurrentUser = Depends(get_current_user)
):
    """SSE stream. Hydrates unread backlog, then pushes new notifications live."""
    gen = notif_module.stream_for_user(request.app, user.id)
    return EventSourceResponse(gen, ping=15)


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str, user: CurrentUser = Depends(get_current_user)
):
    ok = await asyncio.to_thread(_svc().mark_read, notification_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"status": "ok"}


@router.post("/mark-all-read")
async def mark_all_read(user: CurrentUser = Depends(get_current_user)):
    count = await asyncio.to_thread(_svc().mark_all_read, user.id)
    return {"status": "ok", "count": count}
