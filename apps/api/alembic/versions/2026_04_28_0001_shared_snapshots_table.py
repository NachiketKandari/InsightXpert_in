"""Share-chat snapshots — capability-token-gated frozen views of conversations.

Revision ID: 20260428_0001
Revises: 20260427_0004
Create Date: 2026-04-28

Stores the full viewable payload inline (messages + result rows + dataset
name) so the public viewer never traverses live conversation/messages/
databases rows. ``token`` is the capability (PK, unique by construction).
``revoked_at`` is set to the unix-second timestamp of revocation; non-null
means the snapshot must 404 even if not expired. ``expires_at`` is a unix
seconds wall clock; non-null and ≤ now means expired.

Also adds ``users.sharing_disabled`` so admins can revoke a single user's
ability to publish new snapshots (existing snapshots remain visible until
revoked or expired).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260428_0001"
down_revision = "20260427_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shared_snapshots",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("db_id", sa.String(length=255), nullable=True),
        sa.Column("db_kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_shared_snapshots_owner_user_id",
        "shared_snapshots",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_shared_snapshots_conversation_id",
        "shared_snapshots",
        ["conversation_id"],
    )
    op.add_column(
        "users",
        sa.Column(
            "sharing_disabled",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "sharing_disabled")
    op.drop_index("ix_shared_snapshots_conversation_id", table_name="shared_snapshots")
    op.drop_index("ix_shared_snapshots_owner_user_id", table_name="shared_snapshots")
    op.drop_table("shared_snapshots")
