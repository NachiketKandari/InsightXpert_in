"""Insights list/create/bookmark/delete endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from sqlalchemy import select as sa_select

from ..auth.current_user import CurrentUser, get_current_user, require_admin
from ..db.engine import get_engine
from ..insights.service import InsightService
from ..orchestration.table import conversations, messages

log = logging.getLogger("insightxpert_api.routes.insights")

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


def _svc() -> InsightService:
    return InsightService()


class CreateInsightRequest(BaseModel):
    message_id: str
    user_note: str | None = None


class BookmarkRequest(BaseModel):
    bookmarked: bool


@router.get("/count")
async def insight_count(user: CurrentUser = Depends(get_current_user)):
    count = await _svc().count(user.id)
    return {"count": count}


@router.get("")
async def list_insights(
    user: CurrentUser = Depends(get_current_user),
    bookmarked: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows, total = await asyncio.gather(
        _svc().list_for_user(user.id, bookmarked=bookmarked, limit=limit),
        _svc().count(user.id),
    )
    return {"insights": rows, "total": total}


@router.get("/all")
async def list_insights_admin(
    _admin: CurrentUser = Depends(require_admin),
    limit: int = Query(default=200, ge=1, le=500),
):
    rows = await _svc().list_all(limit=limit)
    return {"insights": rows}


@router.post("")
async def create_insight(
    body: CreateInsightRequest,
    user: CurrentUser = Depends(get_current_user),
):
    def _lookup() -> tuple[dict, str, str]:
        """Resolve message + ownership in thread to avoid blocking the event loop."""
        with get_engine().connect() as conn:
            row = conn.execute(
                sa_select(messages.c.id, messages.c.conversation_id, messages.c.content)
                .where(messages.c.id == body.message_id)
            ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="message not found")

        msg = dict(row._mapping)
        conversation_id: str = msg["conversation_id"]
        msg_content: str = msg.get("content", "") or ""

        with get_engine().connect() as conn:
            conv = conn.execute(
                sa_select(conversations.c.id).where(
                    conversations.c.id == conversation_id,
                    conversations.c.user_id == user.id,
                )
            ).first()
        if conv is None:
            raise HTTPException(status_code=403, detail="access denied")

        return msg, conversation_id, msg_content

    msg, conversation_id, msg_content = await asyncio.to_thread(_lookup)

    result = await _svc().create(
        user_id=user.id,
        conversation_id=conversation_id,
        message_id=body.message_id,
        content=msg_content,
        summary=None,
        title=None,
        user_note=body.user_note,
        source="manual",
    )
    return {"status": "ok", "id": result["id"]}


@router.patch("/{insight_id}/bookmark")
async def bookmark_insight(
    insight_id: str,
    body: BookmarkRequest,
    user: CurrentUser = Depends(get_current_user),
):
    ok = await _svc().bookmark(insight_id, user.id, body.bookmarked)
    if not ok:
        raise HTTPException(status_code=404, detail="insight not found")
    return {"status": "ok"}


@router.delete("/{insight_id}")
async def delete_insight(
    insight_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    ok = await _svc().delete(insight_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="insight not found")
    return {"status": "ok"}
