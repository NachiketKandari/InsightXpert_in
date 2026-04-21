"""Tiny dataclass-based repository over the ``prompt_templates`` table.

The resolver calls ``get(name)``; admin CRUD routes (Cluster 3) call ``upsert``
and ``list_all``. Keeping this separate from the resolver makes the DB edge
easy to mock in unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time as _now

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db.engine import get_engine
from ..orchestration.table import prompt_templates


@dataclass(frozen=True)
class PromptRow:
    name: str
    content: str
    is_active: bool
    description: str | None = None


def get(name: str) -> PromptRow | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(prompt_templates).where(prompt_templates.c.name == name)
        ).first()
    if row is None:
        return None
    return PromptRow(
        name=row.name,
        content=row.content,
        is_active=bool(row.is_active),
        description=row.description,
    )


def upsert(
    name: str,
    content: str,
    *,
    description: str | None = None,
    is_active: bool = True,
) -> PromptRow:
    """Insert or update a prompt template row.

    Uses SQLite's ``ON CONFLICT`` to atomically upsert; the ``created_at`` is
    preserved on update via ``DO UPDATE`` targeting only the mutable columns.
    """
    now = int(_now())
    stmt = sqlite_insert(prompt_templates).values(
        name=name,
        content=content,
        description=description,
        is_active=1 if is_active else 0,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[prompt_templates.c.name],
        set_={
            "content": content,
            "description": description,
            "is_active": 1 if is_active else 0,
            "updated_at": now,
        },
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)
    row = get(name)
    assert row is not None, "upsert must produce a row"
    return row


def delete_one(name: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(delete(prompt_templates).where(prompt_templates.c.name == name))
