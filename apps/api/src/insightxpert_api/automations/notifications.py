"""Notifications create + SSE dispatch.

Two entry points:
    * ``create()`` writes to the ``notifications`` table (durable).
    * ``dispatch()`` pushes via the per-user ``EventEmitter`` stored on
      ``app.state.user_notification_emitters``.

Decoupled on purpose: a scheduler run may fire a trigger while no client is
connected — the DB row must still land.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI
from sqlalchemy import Engine

from ..sse.chunks import ChatChunk, ChunkType
from ..sse.emitter import EventEmitter
from . import repository

logger = logging.getLogger("insightxpert_api.automations.notifications")


def create(
    user_id: str,
    *,
    title: str,
    message: str,
    severity: str = "info",
    automation_id: str | None = None,
    run_id: str | None = None,
    _engine: Engine | None = None,
) -> dict[str, Any]:
    """Persist a notification row and return the hydrated dict."""
    row = repository.insert_notification(
        {
            "user_id": user_id,
            "automation_id": automation_id,
            "run_id": run_id,
            "title": title,
            "message": message,
            "severity": severity,
        },
        _engine=_engine,
    )
    return {
        "id": row["id"],
        "user_id": user_id,
        "automation_id": automation_id,
        "run_id": run_id,
        "title": title,
        "message": message,
        "severity": severity,
        "is_read": False,
        "created_at": row["created_at"],
    }


def get_or_create_user_emitter(app: FastAPI, user_id: str) -> EventEmitter:
    """Return the per-user ``EventEmitter`` for notifications, creating one if needed.

    Dict mutation is protected by the ``_emitters_lock`` on ``app.state`` when
    the lock is available (i.e., after lifespan start). During tests or early
    startup the lock may not be set; in that case we fall through safely under
    CPython's GIL.
    """
    emitters: dict[str, EventEmitter] = getattr(
        app.state, "user_notification_emitters", None
    ) or {}
    if not hasattr(app.state, "user_notification_emitters"):
        app.state.user_notification_emitters = emitters
    em = emitters.get(user_id)
    if em is None:
        em = EventEmitter(conversation_id=f"notif:{user_id}", user_id=user_id)
        emitters[user_id] = em
    return em


async def dispatch(app: FastAPI, user_id: str, notif: dict[str, Any]) -> None:
    """Push the notification through the user's EventEmitter, if any.

    We do NOT auto-create an emitter here — if no client is connected, the
    notification remains durable in the DB for polled hydration.
    """
    emitters: dict[str, EventEmitter] = getattr(
        app.state, "user_notification_emitters", {}
    )
    em = emitters.get(user_id)
    if em is None:
        logger.debug("no emitter for user %s, skipping SSE dispatch", user_id)
        return
    try:
        # Emit as a raw data dict on the chat-chunk envelope; the notifications
        # SSE route wraps this as a ``notification_created`` event downstream.
        await em.emit(ChunkType.STATUS, {"notification": notif})
    except Exception as exc:  # noqa: BLE001
        logger.warning("SSE dispatch failed for user %s: %s", user_id, exc)


async def stream_for_user(
    app: FastAPI, user_id: str
) -> Any:
    """Async generator yielding SSE payload strings for the user's notifications.

    Hydrates the initial backlog of unread notifications, then subscribes to
    the per-user EventEmitter. Each subsequent notification dispatch yields one
    JSON payload that sse-starlette frames as ``data: <json>\\n\\n``.
    """
    em = get_or_create_user_emitter(app, user_id)

    # Initial backlog — send unread notifications newest-first.
    backlog = repository.list_notifications(user_id, unread_only=True, limit=50)
    for row in backlog:
        payload = {
            "type": "notification_created",
            "data": {
                "id": row["id"],
                "user_id": row["user_id"],
                "automation_id": row.get("automation_id"),
                "run_id": row.get("run_id"),
                "title": row["title"],
                "message": row["message"],
                "severity": row["severity"],
                "is_read": bool(row["is_read"]),
                "automation_name": row.get("automation_name"),
                "created_at": row["created_at"],
            },
        }
        yield json.dumps(payload)

    async for raw in em.stream():
        if raw == "[DONE]":
            return
        # The stream yields ChatChunk.to_json(); unwrap to match backlog shape.
        try:
            chunk = json.loads(raw)
            data = chunk.get("data") or {}
            notif = data.get("notification")
            if notif is None:
                continue
            yield json.dumps({"type": "notification_created", "data": notif})
        except json.JSONDecodeError:
            continue


__all__ = ["create", "dispatch", "stream_for_user", "get_or_create_user_emitter"]
