"""Metrics service: insert a query_metrics row per chat turn + update thumbs.

All DB calls are synchronous (SQLAlchemy Core against SQLite); async callers
MUST wrap via ``asyncio.to_thread`` per spec O13.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import desc, select, update

from ..db.engine import get_engine
from ..logging import get_logger
from .table import query_metrics

log = get_logger("metrics")


def record_turn(
    *,
    user_id: str,
    conversation_id: str,
    db_id: str | None,
    question: str,
    final_sql: str | None,
    agent_mode: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    duration_ms: int | None,
    stage_timings: dict[str, Any] | None = None,
    agent_trace_summary: dict[str, Any] | None = None,
) -> str:
    """Insert one row into query_metrics. Returns the new row id."""
    row_id = uuid.uuid4().hex
    now = int(time.time())
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                query_metrics.insert().values(
                    id=row_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    db_id=db_id,
                    question=question,
                    final_sql=final_sql,
                    agent_mode=agent_mode,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    duration_ms=duration_ms,
                    thumbs=None,
                    stage_timings_json=(
                        json.dumps(stage_timings) if stage_timings is not None else None
                    ),
                    agent_trace_summary_json=(
                        json.dumps(agent_trace_summary)
                        if agent_trace_summary is not None
                        else None
                    ),
                    created_at=now,
                )
            )
    except Exception as exc:  # noqa: BLE001 — best-effort, never user-facing
        log.error("metrics.record_turn_failed", error=str(exc), error_type=type(exc).__name__)
    return row_id


def update_thumbs(conversation_id: str, thumbs: str | None) -> None:
    """Update the most-recent query_metrics row for this conversation.

    ``thumbs`` must be 'up', 'down', or None. The row selected is the one
    with the largest created_at for the given conversation_id.
    """
    if thumbs not in (None, "up", "down"):
        raise ValueError(f"invalid thumbs value: {thumbs!r}")
    try:
        engine = get_engine()
        with engine.begin() as conn:
            row = conn.execute(
                select(query_metrics.c.id)
                .where(query_metrics.c.conversation_id == conversation_id)
                .order_by(desc(query_metrics.c.created_at))
                .limit(1)
            ).first()
            if row is None:
                return
            conn.execute(
                update(query_metrics)
                .where(query_metrics.c.id == row[0])
                .values(thumbs=thumbs)
            )
    except Exception as exc:  # noqa: BLE001
        log.error("metrics.update_thumbs_failed", error=str(exc), error_type=type(exc).__name__)
