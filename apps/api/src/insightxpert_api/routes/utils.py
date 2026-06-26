"""Shared route-layer utilities — timestamp conversion and cursor pagination."""

from __future__ import annotations

import base64
import time
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def ts(raw: int | None) -> int:
    """Convert epoch-seconds integer to milliseconds for JS. Zero/null -> now."""
    val = raw or 0
    return (val * 1000) if val > 0 else int(time.time() * 1000)


def decode_cursor(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_s, ident = decoded.split(":", 1)
        return int(ts_s), ident
    except Exception:
        return None


def encode_cursor(created_at: int, ident: str) -> str:
    return base64.urlsafe_b64encode(f"{created_at}:{ident}".encode()).decode()


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def cursor_where(table, cursor: str | None) -> ColumnElement | None:
    decoded = decode_cursor(cursor)
    if decoded is None:
        return None
    ts_val, ident = decoded
    return or_(
        table.c.created_at < ts_val,
        and_(
            table.c.created_at == ts_val,
            table.c.id < ident,
        ),
    )
