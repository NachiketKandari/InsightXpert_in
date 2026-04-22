"""Tier 1 full-schema mode — per-DB pipeline_mode_default column.

Adds a nullable TEXT column ``pipeline_mode_default`` to the ``databases``
table. Values: ``"linked"`` | ``"full_schema"`` | NULL (inherit system
default, which is ``"linked"``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260424_0001"
down_revision: str | None = "20260422_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite requires batch_alter_table for ADD COLUMN with CHECK constraints;
    # a plain nullable TEXT column with no default is fine via add_column.
    op.add_column(
        "databases",
        sa.Column("pipeline_mode_default", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("databases") as batch:
        batch.drop_column("pipeline_mode_default")
