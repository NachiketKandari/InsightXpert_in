"""Users repository — thin SQL layer, no business logic.

All email storage is lowercased at write time; lookups lower() at the app
boundary so behavior is case-insensitive.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update

from ..db.engine import get_engine
from .models import UserWithHash
from .table import users as users_table


def _row_to_user_with_hash(row) -> UserWithHash:
    return UserWithHash(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        role=row.role,
        is_active=bool(row.is_active),
        must_change_password=bool(row.must_change_password),
        sessions_valid_after=row.sessions_valid_after,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_seen_at=row.last_seen_at,
    )


def insert_user(u: UserWithHash) -> None:
    with get_engine().begin() as conn:
        conn.execute(insert(users_table).values(
            id=u.id,
            email=u.email.lower(),
            password_hash=u.password_hash,
            role=u.role,
            is_active=1 if u.is_active else 0,
            must_change_password=1 if u.must_change_password else 0,
            sessions_valid_after=u.sessions_valid_after,
            created_at=u.created_at,
            updated_at=u.updated_at,
            last_seen_at=u.last_seen_at,
        ))


def get_by_id(user_id: str) -> UserWithHash | None:
    with get_engine().connect() as conn:
        row = conn.execute(select(users_table).where(users_table.c.id == user_id)).first()
    return _row_to_user_with_hash(row) if row else None


def get_by_email(email: str) -> UserWithHash | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(users_table).where(users_table.c.email == email.lower())
        ).first()
    return _row_to_user_with_hash(row) if row else None


def list_users() -> list[UserWithHash]:
    with get_engine().connect() as conn:
        rows = conn.execute(select(users_table).order_by(users_table.c.created_at.asc())).all()
    return [_row_to_user_with_hash(r) for r in rows]


def update_user(user_id: str, patch: dict[str, Any]) -> None:
    if not patch:
        return
    with get_engine().begin() as conn:
        conn.execute(update(users_table).where(users_table.c.id == user_id).values(**patch))


def delete_user(user_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(delete(users_table).where(users_table.c.id == user_id))


def count_active_admins() -> int:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(func.count()).select_from(users_table).where(
                (users_table.c.role == "admin") & (users_table.c.is_active == 1)
            )
        ).scalar()
    return int(row or 0)
