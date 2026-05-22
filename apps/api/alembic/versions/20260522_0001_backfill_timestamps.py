"""Backfill zero timestamps in conversations and messages tables.

Revision ID: 20260522_0001
Revises: 20260521_0002
Create Date: 2026-05-22
"""

from __future__ import annotations

import time

import sqlalchemy as sa
from alembic import op

revision = "20260522_0001"
down_revision: str | None = "20260521_0002"
branch_labels: str | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    now = int(time.time())

    # conversations
    op.execute(
        sa.text(
            "UPDATE conversations SET created_at = :now WHERE created_at IS NULL OR created_at = 0"
        ).bindparams(now=now)
    )
    op.execute(
        sa.text(
            "UPDATE conversations SET updated_at = :now WHERE updated_at IS NULL OR updated_at = 0"
        ).bindparams(now=now)
    )

    # messages
    op.execute(
        sa.text(
            "UPDATE messages SET created_at = :now WHERE created_at IS NULL OR created_at = 0"
        ).bindparams(now=now)
    )


def downgrade() -> None:
    pass
