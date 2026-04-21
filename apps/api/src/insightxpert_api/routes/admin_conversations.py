"""/api/v1/admin/conversations — cursor-paginated conversation list + detail + delete.

Cursor shape matches /admin/metrics (base64 ``created_at:id``, descending).
JOINs users for ``user_email`` on list. Detail returns parsed ``chunks_json``
as a list (pre-parsed for FE ThinkingTrace).
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select

from ..auth.current_user import CurrentUser, require_admin
from ..db.engine import get_engine
from ..orchestration.table import conversations, messages
from ..users.table import users as users_table

router = APIRouter(prefix="/api/v1/admin/conversations", tags=["admin-conversations"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _decode(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_s, ident = decoded.split(":", 1)
        return int(ts_s), ident
    except Exception:  # noqa: BLE001
        return None


def _encode(created_at: int, ident: str) -> str:
    return base64.urlsafe_b64encode(f"{created_at}:{ident}".encode()).decode()


def _list(
    user_id: str | None,
    db_id: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    msg_count = (
        select(
            messages.c.conversation_id.label("cid"),
            func.count(messages.c.id).label("cnt"),
        )
        .group_by(messages.c.conversation_id)
        .subquery()
    )
    q = (
        select(
            conversations.c.id,
            conversations.c.user_id,
            conversations.c.db_id,
            conversations.c.title,
            conversations.c.created_at,
            conversations.c.updated_at,
            users_table.c.email.label("user_email"),
            func.coalesce(msg_count.c.cnt, 0).label("message_count"),
        )
        .select_from(
            conversations
            .outerjoin(users_table, users_table.c.id == conversations.c.user_id)
            .outerjoin(msg_count, msg_count.c.cid == conversations.c.id)
        )
        .order_by(conversations.c.created_at.desc(), conversations.c.id.desc())
        .limit(limit + 1)
    )
    if user_id:
        q = q.where(conversations.c.user_id == user_id)
    if db_id:
        q = q.where(conversations.c.db_id == db_id)
    decoded = _decode(cursor)
    if decoded:
        ts, ident = decoded
        q = q.where(
            or_(
                conversations.c.created_at < ts,
                and_(
                    conversations.c.created_at == ts,
                    conversations.c.id < ident,
                ),
            )
        )
    with get_engine().connect() as conn:
        rows = conn.execute(q).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode(rows[-1].created_at, rows[-1].id) if more and rows else None
    )
    return {
        "rows": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "user_email": r.user_email,
                "db_id": r.db_id,
                "title": r.title,
                "message_count": int(r.message_count or 0),
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


def _detail(conv_id: str) -> dict[str, Any] | None:
    q = (
        select(
            conversations.c.id,
            conversations.c.user_id,
            conversations.c.db_id,
            conversations.c.title,
            conversations.c.created_at,
            conversations.c.updated_at,
            users_table.c.email.label("user_email"),
        )
        .select_from(
            conversations.outerjoin(
                users_table, users_table.c.id == conversations.c.user_id
            )
        )
        .where(conversations.c.id == conv_id)
    )
    mq = (
        select(messages)
        .where(messages.c.conversation_id == conv_id)
        .order_by(messages.c.created_at.asc(), messages.c.id.asc())
    )
    with get_engine().connect() as conn:
        row = conn.execute(q).first()
        if row is None:
            return None
        msg_rows = conn.execute(mq).all()

    parsed_msgs: list[dict[str, Any]] = []
    for m in msg_rows:
        chunks: list[Any] | None = None
        if m.chunks_json:
            try:
                loaded = json.loads(m.chunks_json)
                if isinstance(loaded, list):
                    chunks = loaded
            except Exception:  # noqa: BLE001
                chunks = None
        parsed_msgs.append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
                "chunks_json": chunks,
                "created_at": m.created_at,
            }
        )
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_email": row.user_email,
        "db_id": row.db_id,
        "title": row.title,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "messages": parsed_msgs,
    }


def _delete(conv_id: str) -> bool:
    with get_engine().begin() as conn:
        existing = conn.execute(
            select(conversations.c.id).where(conversations.c.id == conv_id)
        ).first()
        if existing is None:
            return False
        conn.execute(delete(messages).where(messages.c.conversation_id == conv_id))
        conn.execute(delete(conversations).where(conversations.c.id == conv_id))
    return True


@router.get("/")
async def list_conversations(
    user_id: str | None = None,
    db_id: str | None = None,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    limit = max(1, min(limit, _MAX_LIMIT))
    return await asyncio.to_thread(_list, user_id, db_id, cursor, limit)


@router.get("/{conv_id}")
async def get_conversation(
    conv_id: str,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    result = await asyncio.to_thread(_detail, conv_id)
    if result is None:
        raise HTTPException(status_code=404, detail="not_found")
    return result


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: str,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    ok = await asyncio.to_thread(_delete, conv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"deleted": True}
