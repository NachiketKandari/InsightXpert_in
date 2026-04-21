"""/api/v1/admin/metrics — cursor-paginated query_metrics.

Same pagination shape as /admin/audit. Filters per spec §5.3:
    user, db, thumbs, agent_mode, from, to
"""

from __future__ import annotations

import asyncio
import base64

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select

from ..auth.current_user import CurrentUser, require_admin
from ..db.engine import get_engine
from ..metrics.table import query_metrics

router = APIRouter(prefix="/api/v1/admin/metrics", tags=["admin-metrics"])

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
    decoded = _decode(cursor)
    if decoded:
        ts, ident = decoded
        q = q.where(
            or_(
                query_metrics.c.created_at < ts,
                and_(
                    query_metrics.c.created_at == ts,
                    query_metrics.c.id < ident,
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
    limit: int = _DEFAULT_LIMIT,
    cu: CurrentUser = Depends(require_admin),
) -> dict:
    limit = max(1, min(limit, _MAX_LIMIT))
    return await asyncio.to_thread(
        _fetch, user, db, thumbs, agent_mode, from_, to, cursor, limit
    )
