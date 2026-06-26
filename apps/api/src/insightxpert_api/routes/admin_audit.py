"""/api/v1/admin/audit — cursor-paginated audit log.

Order: (created_at desc, id desc). Cursor encodes the last row in the previous
page; page fetch requests strictly less than that key so there's no overlap.

Cursor format: ``base64url("<created_at>:<id>")``. Opaque to the client.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ..audit.table import audit_log
from ..auth.current_user import CurrentUser, require_admin
from ..db.engine import get_engine

from .utils import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit, cursor_where, decode_cursor, encode_cursor

router = APIRouter(prefix="/api/v1/admin/audit", tags=["admin-audit"])


def _query(
    user: str | None,
    action: str | None,
    from_: int | None,
    to: int | None,
    cursor: str | None,
    limit: int,
):
    q = (
        select(audit_log)
        .order_by(audit_log.c.created_at.desc(), audit_log.c.id.desc())
        .limit(limit + 1)
    )
    if user:
        q = q.where(audit_log.c.user_id == user)
    if action:
        q = q.where(audit_log.c.method == action.upper())
    if from_ is not None:
        q = q.where(audit_log.c.created_at >= from_)
    if to is not None:
        q = q.where(audit_log.c.created_at <= to)
    cw = cursor_where(audit_log, cursor)
    if cw is not None:
        q = q.where(cw)
    return q


def _fetch(
    user: str | None,
    action: str | None,
    from_: int | None,
    to: int | None,
    cursor: str | None,
    limit: int,
) -> dict:
    q = _query(user, action, from_, to, cursor, limit)
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
async def list_audit(
    user: str | None = None,
    action: str | None = None,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cu: CurrentUser = Depends(require_admin),
) -> dict:
    limit = clamp_limit(limit)
    return await asyncio.to_thread(
        _fetch, user, action, from_, to, cursor, limit
    )
