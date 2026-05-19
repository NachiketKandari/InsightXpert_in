"""add join_graph_json, user_hints columns and profile_overrides table.

Revision ID: 20260519_0001
Revises: 20260428_0002
Create Date: 2026-05-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260519_0001"
down_revision = "20260428_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- database_profiles additions ---
    op.add_column(
        "database_profiles",
        sa.Column("join_graph_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "database_profiles",
        sa.Column("user_hints", sa.Text(), nullable=True),
    )

    # --- profile_overrides table ---
    op.create_table(
        "profile_overrides",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("db_id", sa.String(length=255), nullable=False),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("column_name", sa.String(length=255), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("edited_by", sa.String(length=36), nullable=False),
        sa.Column("edited_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "db_id", "table_name", "column_name", "field_path",
            name="uq_profile_override",
        ),
    )
    op.create_index(
        "ix_profile_overrides_db_id",
        "profile_overrides",
        ["db_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_overrides_db_id", table_name="profile_overrides")
    op.drop_table("profile_overrides")
    op.drop_column("database_profiles", "user_hints")
    op.drop_column("database_profiles", "join_graph_json")
