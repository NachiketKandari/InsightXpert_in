"""Insights repository — thin SQLAlchemy Core SQL layer.

One function per query. No business logic (lives in ``service.py``). Returns
plain dicts. Follows the same pattern as ``automations/repository.py``.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import and_, delete, desc, func, insert, select, update

from ..db.engine import get_engine
from ..orchestration.table import insights
from ..users.table import users as users_table


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> int:
    return int(time.time())


def insert_insight(
    *,
    user_id: str,
    conversation_id: str,
    message_id: str | None = None,
    content: str = "",
    summary: str | None = None,
    title: str | None = None,
    user_note: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": _uuid(),
        "user_id": user_id,
        "org_id": None,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "title": title,
        "summary": summary,
        "content": content,
        "categories": json.dumps([]),
        "enrichment_task_count": 0,
        "is_bookmarked": 0,
        "user_note": user_note,
        "source": source,
        "created_at": _now(),
    }
    with get_engine().begin() as conn:
        conn.execute(insert(insights).values(**values))
    return values


def list_insights(
    user_id: str,
    *,
    bookmarked: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = (
        select(insights)
        .where(insights.c.user_id == user_id)
    )
    if bookmarked:
        stmt = stmt.where(insights.c.is_bookmarked.is_(True))
    stmt = stmt.order_by(desc(insights.c.created_at)).limit(limit)
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [_deserialize(r._mapping) for r in rows]


def list_all_insights(
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    stmt = (
        select(
            insights,
            users_table.c.email.label("user_email"),
        )
        .select_from(
            insights.outerjoin(
                users_table, users_table.c.id == insights.c.user_id
            )
        )
        .order_by(desc(insights.c.created_at))
        .limit(limit)
    )
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [_deserialize(r._mapping) for r in rows]


def count_insights(user_id: str) -> int:
    with get_engine().connect() as conn:
        result = conn.execute(
            select(func.count())
            .select_from(insights)
            .where(insights.c.user_id == user_id)
        ).scalar()
    return int(result or 0)


def update_bookmark(insight_id: str, user_id: str, bookmarked: bool) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(
            update(insights)
            .where(
                and_(
                    insights.c.id == insight_id,
                    insights.c.user_id == user_id,
                )
            )
            .values(is_bookmarked=1 if bookmarked else 0)
        )
    return (result.rowcount or 0) > 0


def delete_insight(insight_id: str, user_id: str) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(
            delete(insights).where(
                and_(
                    insights.c.id == insight_id,
                    insights.c.user_id == user_id,
                )
            )
        )
    return (result.rowcount or 0) > 0


def _deserialize(row: dict[str, Any]) -> dict[str, Any]:
    """Convert persisted columns to the shape the frontend expects."""
    d = dict(row)
    cats = d.get("categories")
    if isinstance(cats, str):
        try:
            d["categories"] = json.loads(cats)
        except (json.JSONDecodeError, TypeError):
            d["categories"] = []
    if cats is None:
        d["categories"] = []
    d["is_bookmarked"] = bool(d.get("is_bookmarked", 0))
    return d


__all__ = [
    "insert_insight",
    "list_insights",
    "list_all_insights",
    "count_insights",
    "update_bookmark",
    "delete_insight",
]
