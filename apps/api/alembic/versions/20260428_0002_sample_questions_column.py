"""add sample_questions JSONB column to database_profiles.

Revision ID: 20260428_0002
Revises: 20260428_0001
Create Date: 2026-04-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_0002"
down_revision = "20260428_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.add_column(
            "database_profiles",
            sa.Column("sample_questions", sa.dialects.postgresql.JSONB(), nullable=True),
        )
    else:
        op.add_column(
            "database_profiles",
            sa.Column("sample_questions", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("database_profiles", "sample_questions")
