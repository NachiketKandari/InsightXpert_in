"""SQLAlchemy table declaration for ``database_profiles``.

Persistence backing for ``services.profile_service.ProfileService``. One row
per ``(db_id, profile_kind)`` — re-running a kind overwrites.
"""

from __future__ import annotations

import sqlalchemy as sa

from ..db.base import metadata


database_profiles = sa.Table(
    "database_profiles",
    metadata,
    sa.Column("db_id", sa.String(length=255), nullable=False),
    sa.Column(
        "profile_kind",
        sa.String(length=32),
        nullable=False,
        server_default="base",
    ),
    sa.Column("owner_user_id", sa.String(length=36), nullable=True),
    sa.Column("profile_json", sa.Text(), nullable=False),
    sa.Column("generated_at", sa.Integer(), nullable=False),
    sa.Column("generated_by", sa.String(length=36), nullable=True),
    sa.Column("input_tokens", sa.Integer(), nullable=True),
    sa.Column("output_tokens", sa.Integer(), nullable=True),
    sa.Column("cost_usd", sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint("db_id", "profile_kind"),
    sa.Index("ix_database_profiles_owner_user_id", "owner_user_id"),
)
