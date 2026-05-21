"""Conversation CRUD routes (DB-backed).

Reads and writes the persistent ``conversations`` / ``messages`` tables so the
sidebar list and conversation detail reflect durable state (survives process
restarts, picked up by admin import scripts, etc.).

All results are scoped by ``user_id`` from the signed session cookie; other
users' rows are invisible by construction. The legacy in-memory
``ConversationStore`` remains in place solely for the live SSE replay buffer
during a chat turn — it is not consulted by these endpoints.

Response shape includes both ``conversation_id`` (legacy tests) and ``id``
(frontend) for the same UUID, plus ``messages`` on detail.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, select, update

from ..auth.current_user import CurrentUser, get_current_user
from ..db.engine import get_engine
from ..orchestration.table import conversations, messages

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class ConversationPatch(BaseModel):
    title: str | None = None
    starred: bool | None = None


def _row_to_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "conversation_id": row.id,
        "title": row.title,
        "starred": bool(row.is_starred),
        "db_id": row.db_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "messages": [],
    }


def _list(user_id: str) -> list[dict[str, Any]]:
    q = (
        select(
            conversations.c.id,
            conversations.c.title,
            conversations.c.is_starred,
            conversations.c.db_id,
            conversations.c.created_at,
            conversations.c.updated_at,
        )
        .where(conversations.c.user_id == user_id)
        .order_by(
            conversations.c.updated_at.desc(),
            conversations.c.created_at.desc(),
        )
        .limit(200)
    )
    with get_engine().connect() as conn:
        rows = conn.execute(q).all()
    return [_row_to_summary(r) for r in rows]


def _detail(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    cq = (
        select(
            conversations.c.id,
            conversations.c.title,
            conversations.c.is_starred,
            conversations.c.db_id,
            conversations.c.created_at,
            conversations.c.updated_at,
        )
        .where(conversations.c.id == conversation_id)
        .where(conversations.c.user_id == user_id)
    )
    mq = (
        select(messages)
        .where(messages.c.conversation_id == conversation_id)
        # When the snapshot writer inserts user+assistant at the same
        # epoch-second, break the tie by role so "user" sorts before
        # "assistant" (desc: 'u' > 'a'). Fallback to id for stability.
        .order_by(
            messages.c.created_at.asc(),
            messages.c.role.desc(),
            messages.c.id.asc(),
        )
    )
    with get_engine().connect() as conn:
        crow = conn.execute(cq).first()
        if crow is None:
            return None
        mrows = conn.execute(mq).all()

    out = _row_to_summary(crow)
    parsed: list[dict[str, Any]] = []
    for m in mrows:
        chunks: list[Any] | None = None
        if m.chunks_json:
            try:
                loaded = json.loads(m.chunks_json)
                if isinstance(loaded, list):
                    chunks = loaded
            except Exception:  # noqa: BLE001
                chunks = None
        parsed.append(
            {
                "id": m.id,
                "message_id": m.id,
                "role": m.role,
                "content": m.content,
                "chunks": chunks or [],
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
                "input_tokens": m.tokens_in,
                "output_tokens": m.tokens_out,
                "generation_time_ms": m.generation_time_ms,
                "created_at": m.created_at,
            }
        )
    out["messages"] = parsed
    # Replay buffer: flatten every message's chunk list so the FE can
    # re-render a finished turn on reload. Matches the legacy in-memory
    # ConversationStore shape (``conversation.chunks``).
    flat_chunks: list[Any] = []
    for m in parsed:
        flat_chunks.extend(m["chunks"])
    out["chunks"] = flat_chunks
    return out


def _patch(
    user_id: str,
    conversation_id: str,
    *,
    title: str | None,
    starred: bool | None,
) -> dict[str, Any] | None:
    values: dict[str, Any] = {}
    if title is not None:
        values["title"] = title[:255]
    if starred is not None:
        values["is_starred"] = 1 if starred else 0
    with get_engine().begin() as conn:
        existing = conn.execute(
            select(conversations.c.id)
            .where(conversations.c.id == conversation_id)
            .where(conversations.c.user_id == user_id)
        ).first()
        if existing is None:
            return None
        if values:
            conn.execute(
                update(conversations)
                .where(conversations.c.id == conversation_id)
                .where(conversations.c.user_id == user_id)
                .values(**values)
            )
    return _detail(user_id, conversation_id)


def _delete_one(user_id: str, conversation_id: str) -> bool:
    with get_engine().begin() as conn:
        existing = conn.execute(
            select(conversations.c.id)
            .where(conversations.c.id == conversation_id)
            .where(conversations.c.user_id == user_id)
        ).first()
        if existing is None:
            return False
        conn.execute(
            delete(messages).where(messages.c.conversation_id == conversation_id)
        )
        conn.execute(
            delete(conversations)
            .where(conversations.c.id == conversation_id)
            .where(conversations.c.user_id == user_id)
        )
    return True


@router.get("")
async def list_conversations(
    cu: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list, cu.id)


def _search(user_id: str, query: str, limit: int = 50) -> list[dict[str, Any]]:
    needle = f"%{query.strip()}%"
    q = (
        select(
            conversations.c.id,
            conversations.c.title,
            conversations.c.is_starred,
            conversations.c.db_id,
            conversations.c.created_at,
            conversations.c.updated_at,
        )
        .where(conversations.c.user_id == user_id)
        .where(conversations.c.title.ilike(needle))
        .order_by(
            conversations.c.updated_at.desc(),
            conversations.c.created_at.desc(),
        )
        .limit(limit)
    )
    with get_engine().connect() as conn:
        rows = conn.execute(q).all()
    return [_row_to_summary(r) for r in rows]


@router.get("/search")
async def search_conversations(
    q: str,
    cu: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    if len(q.strip()) < 2:
        return []
    return await asyncio.to_thread(_search, cu.id, q)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    result = await asyncio.to_thread(_detail, cu.id, conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="not_found")
    return result


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: str,
    body: ConversationPatch,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    result = await asyncio.to_thread(
        _patch,
        cu.id,
        conversation_id,
        title=body.title,
        starred=body.starred,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="not_found")
    return result


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    cu: CurrentUser = Depends(get_current_user),
) -> Response:
    ok = await asyncio.to_thread(_delete_one, cu.id, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return Response(status_code=204)
