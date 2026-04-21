"""`audit_log` table (SQLAlchemy Core).

One row per audited request (POST/PUT/PATCH/DELETE). `user_id` is nullable so
failed/unauth requests (login attempts, etc.) still record. Timestamps are
unix-seconds integers to match the rest of the stores.
"""

from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String, Table, Text

from ..db.base import metadata

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=True),
    Column("method", String(8), nullable=False),
    Column("path", String(512), nullable=False),
    Column("resource_type", String(64), nullable=True),
    Column("resource_id", String(128), nullable=True),
    Column("status_code", Integer, nullable=False),
    Column("ip", String(64), nullable=True),
    Column("user_agent", Text, nullable=True),
    Column("created_at", Integer, nullable=False),
)

Index("ix_audit_log_created_at", audit_log.c.created_at.desc())
Index(
    "ix_audit_log_user_id_created_at",
    audit_log.c.user_id,
    audit_log.c.created_at.desc(),
)
