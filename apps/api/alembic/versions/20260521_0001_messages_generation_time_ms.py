"""add generation_time_ms column to messages table.

Revision ID: 20260521_0001
Revises: 20260519_0001
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260521_0001"
down_revision = "20260519_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("generation_time_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "generation_time_ms")
