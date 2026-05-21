"""Conversation snapshot persistence for chat turns (Path C).

Called from the chat route's background hook alongside ``metrics.record_turn``.
Upserts a ``conversations`` row and appends user + assistant ``messages`` rows
(with ``chunks_json`` populated on the assistant row) in a single transaction.

In-memory ``ConversationStore`` continues to serve the live SSE replay buffer;
this module is the durable audit/admin surface.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import select, update

from ..db.engine import get_engine
from ..logging import get_logger
from ..users.table import users as users_table
from .table import conversations, messages

log = get_logger("orchestration")


def record_conversation_snapshot(
    *,
    user_id: str,
    conversation_id: str,
    db_id: str | None,
    user_message: str,
    assistant_message: str,
    chunks: list[dict[str, Any]],
    tokens_in: int | None,
    tokens_out: int | None,
    generation_time_ms: int | None = None,
) -> None:
    """Upsert conversations row + append user + assistant message rows.

    Best-effort: failures are logged and swallowed so they never surface to
    the chat turn. If ``user_id`` is not present in ``users`` (legacy session),
    we log and skip — conversations.user_id is FK-like and we don't want
    orphan rows or crashes.
    """
    now = int(time.time())
    try:
        engine = get_engine()
        with engine.begin() as conn:
            # Guard: user must exist.
            uid_row = conn.execute(
                select(users_table.c.id).where(users_table.c.id == user_id)
            ).first()
            if uid_row is None:
                log.info(
                    "orchestration.snapshot_skipped_unknown_user",
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                return

            existing = conn.execute(
                select(conversations.c.id).where(conversations.c.id == conversation_id)
            ).first()
            if existing is None:
                title = (user_message or "")[:120]
                conn.execute(
                    conversations.insert().values(
                        id=conversation_id,
                        user_id=user_id,
                        db_id=db_id,
                        title=title,
                        is_starred=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                conn.execute(
                    update(conversations)
                    .where(conversations.c.id == conversation_id)
                    .values(updated_at=now)
                )

            conn.execute(
                messages.insert().values(
                    id=uuid.uuid4().hex,
                    conversation_id=conversation_id,
                    role="user",
                    content=user_message,
                    chunks_json=None,
                    tokens_in=None,
                    tokens_out=None,
                    created_at=now,
                )
            )
            conn.execute(
                messages.insert().values(
                    id=uuid.uuid4().hex,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_message,
                    chunks_json=json.dumps(chunks) if chunks else None,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    generation_time_ms=generation_time_ms,
                    created_at=now,
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "orchestration.snapshot_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            conversation_id=conversation_id,
        )
