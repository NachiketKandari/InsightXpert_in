"""SQLAlchemy table declarations for profiling persistence."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

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
    # DECISION(D-012): JSONB for profiles and chunks — flexible evolving schemas, no migrations for new fields
    sa.Column("profile_json", sa.Text(), nullable=False),
    sa.Column("generated_at", sa.Integer(), nullable=False),
    sa.Column("generated_by", sa.String(length=36), nullable=True),
    sa.Column("input_tokens", sa.Integer(), nullable=True),
    sa.Column("output_tokens", sa.Integer(), nullable=True),
    sa.Column("cost_usd", sa.Float(), nullable=True),
    sa.Column("join_graph_json", sa.Text(), nullable=True),
    sa.Column("user_hints", sa.Text(), nullable=True),
    sa.Column("sample_questions", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=True),
    sa.PrimaryKeyConstraint("db_id", "profile_kind"),
    sa.Index("ix_database_profiles_owner_user_id", "owner_user_id"),
    sa.Index("ix_database_profiles_profile_kind", "profile_kind"),
)

profile_overrides = sa.Table(
    "profile_overrides",
    metadata,
    sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
    sa.Column("db_id", sa.String(length=255), nullable=False),
    sa.Column("table_name", sa.String(length=255), nullable=False),
    sa.Column("column_name", sa.String(length=255), nullable=False),
    sa.Column("field_path", sa.String(length=255), nullable=False),
    sa.Column("value_json", sa.Text(), nullable=False),
    sa.Column("edited_by", sa.String(length=36), nullable=False),
    sa.Column("edited_at", sa.Integer(), nullable=False),
    sa.UniqueConstraint(
        "db_id", "table_name", "column_name", "field_path",
        name="uq_profile_override",
    ),
    sa.Index("ix_profile_overrides_db_id", "db_id"),
)
