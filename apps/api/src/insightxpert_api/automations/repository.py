"""Automations repository — thin SQLAlchemy Core SQL layer.

One function per query. No business logic (lives in ``service.py``). Returns
plain dicts. Mirrors the shape of ``databases/repository.py``.

All writes use a single ``engine.begin()`` transaction; reads use
``engine.connect()``. No ORM session objects are constructed here.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import and_, delete, desc, func, insert, select, update

from ..db.engine import get_engine
from .table import (
    automation_runs,
    automation_triggers,
    automations,
    notifications,
    trigger_templates,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# automations
# ---------------------------------------------------------------------------


def insert_automation(values: dict[str, Any]) -> None:
    with get_engine().begin() as conn:
        conn.execute(insert(automations).values(**values))


def get_automation(automation_id: str) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(automations).where(automations.c.id == automation_id)
        ).first()
    return dict(row._mapping) if row else None


def list_automations(
    *,
    owner_user_id: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(automations)
    if owner_user_id is not None:
        stmt = stmt.where(automations.c.owner_user_id == owner_user_id)
    stmt = stmt.order_by(desc(automations.c.created_at))
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(r._mapping) for r in rows]


def list_for_user_paged(
    user_id: str | None,
    *,
    is_admin: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated variant of list_automations. Returns (rows, total).

    Admins see all rows; non-admins are scoped to their own ``owner_user_id``.
    """
    stmt = select(automations)
    count_stmt = select(func.count()).select_from(automations)
    if not is_admin:
        stmt = stmt.where(automations.c.owner_user_id == user_id)
        count_stmt = count_stmt.where(
            automations.c.owner_user_id == user_id
        )
    stmt = stmt.order_by(desc(automations.c.created_at)).limit(limit).offset(
        offset
    )
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
        total = conn.execute(count_stmt).scalar() or 0
    return [dict(r._mapping) for r in rows], int(total)


def count_for_user(user_id: str) -> int:
    """Count automations owned by ``user_id`` (no admin shortcut)."""
    with get_engine().connect() as conn:
        result = conn.execute(
            select(func.count())
            .select_from(automations)
            .where(automations.c.owner_user_id == user_id)
        ).scalar()
    return int(result or 0)


def update_automation(automation_id: str, values: dict[str, Any]) -> None:
    if not values:
        return
    values = {**values, "updated_at": _now()}
    with get_engine().begin() as conn:
        conn.execute(
            update(automations)
            .where(automations.c.id == automation_id)
            .values(**values)
        )


def delete_automation(automation_id: str) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(
            delete(automations).where(automations.c.id == automation_id)
        )
    return (result.rowcount or 0) > 0


def list_due_automations(now_ts: int) -> list[dict[str, Any]]:
    """Active automations whose next_run_at <= now_ts (or null)."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(automations).where(
                and_(
                    automations.c.is_active.is_(True),
                    (automations.c.next_run_at.is_(None))
                    | (automations.c.next_run_at <= now_ts),
                )
            )
        ).all()
    return [dict(r._mapping) for r in rows]


def list_active_automations() -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(automations).where(automations.c.is_active.is_(True))
        ).all()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# automation_triggers
# ---------------------------------------------------------------------------


def replace_triggers(
    automation_id: str, conditions: list[dict[str, Any]]
) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            delete(automation_triggers).where(
                automation_triggers.c.automation_id == automation_id
            )
        )
        if not conditions:
            return
        rows = []
        for i, cond in enumerate(conditions):
            rows.append(
                {
                    "id": _uuid(),
                    "automation_id": automation_id,
                    "ordinal": i,
                    "type": cond.get("type"),
                    "column": cond.get("column"),
                    "operator": cond.get("operator"),
                    "value": cond.get("value"),
                    "change_percent": cond.get("change_percent"),
                    "scope": cond.get("scope"),
                    "nl_text": cond.get("nl_text"),
                }
            )
        conn.execute(insert(automation_triggers), rows)


def list_triggers(automation_id: str) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(automation_triggers)
            .where(automation_triggers.c.automation_id == automation_id)
            .order_by(automation_triggers.c.ordinal)
        ).all()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# automation_runs
# ---------------------------------------------------------------------------


def insert_run(values: dict[str, Any]) -> dict[str, Any]:
    values = {"id": _uuid(), "created_at": _now(), **values}
    with get_engine().begin() as conn:
        conn.execute(insert(automation_runs).values(**values))
    return values


def list_runs(automation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(automation_runs)
            .where(automation_runs.c.automation_id == automation_id)
            .order_by(desc(automation_runs.c.created_at))
            .limit(limit)
        ).all()
    return [dict(r._mapping) for r in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(automation_runs).where(automation_runs.c.id == run_id)
        ).first()
    return dict(row._mapping) if row else None


# ---------------------------------------------------------------------------
# trigger_templates
# ---------------------------------------------------------------------------


def insert_template(values: dict[str, Any]) -> None:
    with get_engine().begin() as conn:
        conn.execute(insert(trigger_templates).values(**values))


def get_template(template_id: str) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(trigger_templates).where(
                trigger_templates.c.id == template_id
            )
        ).first()
    return dict(row._mapping) if row else None


def list_templates(
    *, owner_user_id: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(trigger_templates)
    if owner_user_id is not None:
        stmt = stmt.where(trigger_templates.c.owner_user_id == owner_user_id)
    stmt = stmt.order_by(desc(trigger_templates.c.created_at))
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(r._mapping) for r in rows]


def list_templates_paged(
    *,
    owner_user_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated variant of list_templates. Returns (rows, total)."""
    stmt = select(trigger_templates)
    count_stmt = select(func.count()).select_from(trigger_templates)
    if owner_user_id is not None:
        stmt = stmt.where(trigger_templates.c.owner_user_id == owner_user_id)
        count_stmt = count_stmt.where(
            trigger_templates.c.owner_user_id == owner_user_id
        )
    stmt = (
        stmt.order_by(desc(trigger_templates.c.created_at))
        .limit(limit)
        .offset(offset)
    )
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
        total = conn.execute(count_stmt).scalar() or 0
    return [dict(r._mapping) for r in rows], int(total)


def update_template(template_id: str, values: dict[str, Any]) -> None:
    if not values:
        return
    values = {**values, "updated_at": _now()}
    with get_engine().begin() as conn:
        conn.execute(
            update(trigger_templates)
            .where(trigger_templates.c.id == template_id)
            .values(**values)
        )


def delete_template(template_id: str) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(
            delete(trigger_templates).where(
                trigger_templates.c.id == template_id
            )
        )
    return (result.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------


def insert_notification(values: dict[str, Any]) -> dict[str, Any]:
    values = {
        "id": _uuid(),
        "is_read": False,
        "created_at": _now(),
        **values,
    }
    with get_engine().begin() as conn:
        conn.execute(insert(notifications).values(**values))
    return values


def list_notifications(
    user_id: str,
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = (
        select(
            notifications,
            automations.c.name.label("automation_name"),
        )
        .select_from(
            notifications.outerjoin(
                automations, notifications.c.automation_id == automations.c.id
            )
        )
        .where(notifications.c.user_id == user_id)
    )
    if unread_only:
        stmt = stmt.where(notifications.c.is_read.is_(False))
    stmt = stmt.order_by(desc(notifications.c.created_at)).limit(limit)
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(r._mapping) for r in rows]


def list_all_notifications(
    *,
    unread_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Admin view: notifications across all users, newest first.

    Used by the admin notifications modal. Joins users + automations for
    display metadata (owner email, automation name).
    """
    from ..users.table import users as users_table

    stmt = (
        select(
            notifications,
            automations.c.name.label("automation_name"),
            users_table.c.email.label("user_email"),
        )
        .select_from(
            notifications.outerjoin(
                automations, notifications.c.automation_id == automations.c.id
            ).outerjoin(
                users_table, users_table.c.id == notifications.c.user_id
            )
        )
    )
    if unread_only:
        stmt = stmt.where(notifications.c.is_read.is_(False))
    stmt = stmt.order_by(desc(notifications.c.created_at)).limit(limit)
    with get_engine().connect() as conn:
        rows = conn.execute(stmt).all()
    return [dict(r._mapping) for r in rows]


def count_unread(user_id: str) -> int:
    with get_engine().connect() as conn:
        result = conn.execute(
            select(func.count())
            .select_from(notifications)
            .where(
                and_(
                    notifications.c.user_id == user_id,
                    notifications.c.is_read.is_(False),
                )
            )
        ).scalar()
    return int(result or 0)


def mark_notification_read(notification_id: str, user_id: str) -> bool:
    with get_engine().begin() as conn:
        result = conn.execute(
            update(notifications)
            .where(
                and_(
                    notifications.c.id == notification_id,
                    notifications.c.user_id == user_id,
                )
            )
            .values(is_read=True)
        )
    return (result.rowcount or 0) > 0


def mark_all_notifications_read(user_id: str) -> int:
    with get_engine().begin() as conn:
        result = conn.execute(
            update(notifications)
            .where(
                and_(
                    notifications.c.user_id == user_id,
                    notifications.c.is_read.is_(False),
                )
            )
            .values(is_read=True)
        )
    return result.rowcount or 0


def get_notification(notification_id: str) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(notifications).where(notifications.c.id == notification_id)
        ).first()
    return dict(row._mapping) if row else None


__all__ = [
    "insert_automation",
    "get_automation",
    "list_automations",
    "update_automation",
    "delete_automation",
    "list_for_user_paged",
    "count_for_user",
    "list_due_automations",
    "list_active_automations",
    "replace_triggers",
    "list_triggers",
    "insert_run",
    "list_runs",
    "get_run",
    "insert_template",
    "get_template",
    "list_templates",
    "list_templates_paged",
    "update_template",
    "delete_template",
    "insert_notification",
    "list_notifications",
    "count_unread",
    "mark_notification_read",
    "mark_all_notifications_read",
    "get_notification",
]
