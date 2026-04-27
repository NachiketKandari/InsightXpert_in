"""Phase 4b — database_profiles table on metadata DB.

Revision ID: 20260427_0004
Revises: 20260427_0003
Create Date: 2026-04-27

Replaces the object-store-backed `ProfileService` with a real Postgres
table so profiles are queryable, joinable, and survive object-store rotation.

Keyed by (db_id, profile_kind) — re-running a kind for the same DB
overwrites the row. `owner_user_id` is recorded for audit / future per-user
visibility but is NOT part of the PK because bundled DBs (owner=NULL) need
to be profilable as well.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260427_0004"
down_revision = "20260427_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "database_profiles",
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
    )
    op.create_index(
        "ix_database_profiles_owner_user_id",
        "database_profiles",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_database_profiles_owner_user_id", table_name="database_profiles")
    op.drop_table("database_profiles")
