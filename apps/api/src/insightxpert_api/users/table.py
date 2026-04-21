"""`users` table definition (SQLAlchemy Core).

Schema matches spec §4. `id` is a uuid4 hex string; all timestamps are
unix-seconds integers to match the rest of our SQLite stores.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Integer, String, Table

from ..db.base import metadata

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", String(512), nullable=False),
    Column("role", String(16), nullable=False),
    Column("is_active", Integer, nullable=False, server_default="1"),
    Column("must_change_password", Integer, nullable=False, server_default="0"),
    Column("sessions_valid_after", Integer, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    Column("last_seen_at", Integer, nullable=True),
    CheckConstraint("role IN ('admin','user')", name="users_role_check"),
)
