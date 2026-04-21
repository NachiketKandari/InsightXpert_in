"""/api/v1/admin/overview — aggregate KPIs + 7d sparkline.

Cached for 30s in-process. The first caller after expiry takes the SQL hit;
concurrent callers may briefly race and each recompute — acceptable at our
scale (single instance, low QPS).
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select

from ..admin import overview_cache
from ..auth.current_user import CurrentUser, require_admin
from ..db.engine import get_engine
from ..metrics.table import query_metrics
from ..users.table import users as users_table

router = APIRouter(prefix="/api/v1/admin/overview", tags=["admin-overview"])

_CACHE_KEY = "overview"


def _compute() -> dict:
    now = int(time.time())
    day_ago = now - 86_400
    week_ago = now - 86_400 * 7

    with get_engine().connect() as conn:
        active_24h = conn.execute(
            select(func.count(distinct(query_metrics.c.user_id))).where(
                query_metrics.c.created_at >= day_ago
            )
        ).scalar_one() or 0
        total_users = conn.execute(
            select(func.count()).select_from(users_table)
        ).scalar_one() or 0
        chats_today = conn.execute(
            select(func.count()).select_from(query_metrics).where(
                query_metrics.c.created_at >= day_ago
            )
        ).scalar_one() or 0
        tokens_today = conn.execute(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(query_metrics.c.tokens_in, 0)
                        + func.coalesce(query_metrics.c.tokens_out, 0)
                    ),
                    0,
                )
            ).where(query_metrics.c.created_at >= day_ago)
        ).scalar_one() or 0

        thumbs_up = conn.execute(
            select(func.count()).select_from(query_metrics).where(
                query_metrics.c.thumbs == "up",
                query_metrics.c.created_at >= week_ago,
            )
        ).scalar_one() or 0
        thumbs_down = conn.execute(
            select(func.count()).select_from(query_metrics).where(
                query_metrics.c.thumbs == "down",
                query_metrics.c.created_at >= week_ago,
            )
        ).scalar_one() or 0

        # 7-day sparkline: per-day chats + tokens. Integer division in SQL
        # gives us the day bucket; SQLite math is fine for our scale.
        bucket = (query_metrics.c.created_at / 86_400).label("day")
        rows = conn.execute(
            select(
                bucket,
                func.count().label("n"),
                func.coalesce(
                    func.sum(
                        func.coalesce(query_metrics.c.tokens_in, 0)
                        + func.coalesce(query_metrics.c.tokens_out, 0)
                    ),
                    0,
                ).label("tok"),
            )
            .where(query_metrics.c.created_at >= week_ago)
            .group_by(bucket)
            .order_by(bucket)
        ).all()
        sparkline = [
            {"day": int(r.day), "chats": int(r.n), "tokens": int(r.tok)}
            for r in rows
        ]

    thumbs_total = thumbs_up + thumbs_down
    thumbs_ratio = (thumbs_up / thumbs_total) if thumbs_total else None

    return {
        "active_users_24h": int(active_24h),
        "total_users": int(total_users),
        "chats_today": int(chats_today),
        "tokens_today": int(tokens_today),
        "thumbs_ratio_7d": thumbs_ratio,
        "sparkline_7d": sparkline,
    }


@router.get("/")
async def overview(cu: CurrentUser = Depends(require_admin)) -> dict:
    return await asyncio.to_thread(
        overview_cache.get_or_compute, _CACHE_KEY, _compute
    )
