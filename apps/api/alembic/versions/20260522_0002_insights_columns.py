"""add user-scoped columns to insights table.

Revision ID: 20260522_0002
Revises: 20260522_0001
Create Date: 2026-05-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260522_0002"
down_revision = "20260522_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insights", sa.Column("user_id", sa.String(length=36), nullable=True))
    op.add_column("insights", sa.Column("org_id", sa.String(length=36), nullable=True))
    op.add_column("insights", sa.Column("message_id", sa.String(length=36), nullable=True))
    op.add_column("insights", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("insights", sa.Column("categories", sa.Text(), nullable=True))
    op.add_column(
        "insights",
        sa.Column("enrichment_task_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "insights",
        sa.Column("is_bookmarked", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("insights", sa.Column("user_note", sa.Text(), nullable=True))
    op.add_column(
        "insights",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="auto"),
    )
    op.create_index("ix_insights_user_created", "insights", ["user_id", sa.text("created_at DESC")])
    op.create_index("ix_insights_conversation_id", "insights", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_insights_conversation_id", table_name="insights")
    op.drop_index("ix_insights_user_created", table_name="insights")
    op.drop_column("insights", "source")
    op.drop_column("insights", "user_note")
    op.drop_column("insights", "is_bookmarked")
    op.drop_column("insights", "enrichment_task_count")
    op.drop_column("insights", "categories")
    op.drop_column("insights", "title")
    op.drop_column("insights", "message_id")
    op.drop_column("insights", "org_id")
    op.drop_column("insights", "user_id")
