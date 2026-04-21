"""/api/v1/admin/audit — cursor-paginated audit log.

Order: (created_at desc, id desc). Cursor encodes the last row in the previous
page; page fetch requests strictly less than that key so there's no overlap.

Cursor format: ``base64url("<created_at>:<id>")``. Opaque to the client.
"""

from __future__ import annotations

import asyncio
import base64

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select

from ..audit.table import audit_log
from ..auth.current_user import CurrentUser, require_admin
from ..db.engine import get_engine

router = APIRouter(prefix="/api/v1/admin/audit", tags=["admin-audit"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _decode(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_s, ident = decoded.split(":", 1)
        return int(ts_s), ident
    except Exception:  # noqa: BLE001 — malformed cursor → ignore, return page 1
        return None


def _encode(created_at: int, ident: str) -> str:
    return base64.urlsafe_b64encode(f"{created_at}:{ident}".encode()).decode()


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
    decoded = _decode(cursor)
    if decoded:
        ts, ident = decoded
        q = q.where(
            or_(
                audit_log.c.created_at < ts,
                and_(
                    audit_log.c.created_at == ts,
                    audit_log.c.id < ident,
                ),
            )
        )
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
        _encode(rows[-1].created_at, rows[-1].id) if more and rows else None
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
    limit: int = _DEFAULT_LIMIT,
    cu: CurrentUser = Depends(require_admin),
) -> dict:
    limit = max(1, min(limit, _MAX_LIMIT))
    return await asyncio.to_thread(
        _fetch, user, action, from_, to, cursor, limit
    )
