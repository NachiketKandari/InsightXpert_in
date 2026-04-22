"""`databases` + `database_shares` tables (SQLAlchemy Core).

Visibility is one of 'private' (owner-only), 'shared' (owner + named users via
database_shares), or 'public' (all users). Bundled BIRD DBs are seeded as
visibility='public' with owner_user_id=NULL in the migration.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    String,
    Table,
)

from ..db.base import metadata

databases_table = Table(
    "databases",
    metadata,
    Column("db_id", String(255), primary_key=True),
    Column("owner_user_id", String(36), nullable=True),
    Column("visibility", String(16), nullable=False),
    Column("size_bytes", Integer, nullable=True),
    Column("created_at", Integer, nullable=False),
    # Tier-1 full-schema mode: per-DB override. NULL = inherit system default
    # (currently "linked"). Values: "linked" | "full_schema".
    Column("pipeline_mode_default", String(32), nullable=True),
    CheckConstraint(
        "visibility IN ('private','shared','public')",
        name="databases_visibility_check",
    ),
)

database_shares = Table(
    "database_shares",
    metadata,
    Column("db_id", String(255), primary_key=True),
    Column("user_id", String(36), primary_key=True),
    Column("created_at", Integer, nullable=False),
)
