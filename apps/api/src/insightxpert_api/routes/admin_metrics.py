"""/api/v1/admin/metrics — cursor-paginated query_metrics.

Same pagination shape as /admin/audit. Filters per spec §5.3:
    user, db, thumbs, agent_mode, from, to
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ..auth.current_user import CurrentUser, require_admin
from ..db.engine import get_engine
from ..metrics.table import query_metrics

from .utils import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit, cursor_where, decode_cursor, encode_cursor

router = APIRouter(prefix="/api/v1/admin/metrics", tags=["admin-metrics"])


def _fetch(
    user: str | None,
    db: str | None,
    thumbs: str | None,
    agent_mode: str | None,
    from_: int | None,
    to: int | None,
    cursor: str | None,
    limit: int,
) -> dict:
    q = (
        select(query_metrics)
        .order_by(query_metrics.c.created_at.desc(), query_metrics.c.id.desc())
        .limit(limit + 1)
    )
    if user:
        q = q.where(query_metrics.c.user_id == user)
    if db:
        q = q.where(query_metrics.c.db_id == db)
    if thumbs:
        q = q.where(query_metrics.c.thumbs == thumbs)
    if agent_mode:
        q = q.where(query_metrics.c.agent_mode == agent_mode)
    if from_ is not None:
        q = q.where(query_metrics.c.created_at >= from_)
    if to is not None:
        q = q.where(query_metrics.c.created_at <= to)
    cw = cursor_where(query_metrics, cursor)
    if cw is not None:
        q = q.where(cw)
    with get_engine().connect() as conn:
        rows = conn.execute(q).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1].created_at, rows[-1].id) if more and rows else None
    )
    return {
        "rows": [dict(r._mapping) for r in rows],
        "next_cursor": next_cursor,
    }


@router.get("/")
async def list_metrics(
    user: str | None = None,
    db: str | None = None,
    thumbs: str | None = None,
    agent_mode: str | None = None,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cu: CurrentUser = Depends(require_admin),
) -> dict:
    limit = clamp_limit(limit)
    return await asyncio.to_thread(
        _fetch, user, db, thumbs, agent_mode, from_, to, cursor, limit
    )
