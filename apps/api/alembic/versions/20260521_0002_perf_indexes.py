"""add performance indexes on databases, conversations, messages, database_profiles.

Revision ID: 20260521_0002
Revises: 20260521_0001
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260521_0002"
down_revision = "20260521_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # databases: owner + visibility lookups (full table scans before).
    op.create_index("ix_databases_owner_user_id", "databases", ["owner_user_id"])
    op.create_index("ix_databases_visibility", "databases", ["visibility"])

    # conversations: sort-avoiding composite for sidebar list.
    op.create_index(
        "ix_conversations_user_updated",
        "conversations",
        ["user_id", sa.text("updated_at DESC"), sa.text("created_at DESC")],
    )

    # messages: sort-avoiding composite for conversation detail.
    op.create_index(
        "ix_messages_conv_created",
        "messages",
        ["conversation_id", "created_at"],
    )

    # database_profiles: profile_kind filter (second PK column).
    op.create_index(
        "ix_database_profiles_profile_kind",
        "database_profiles",
        ["profile_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_database_profiles_profile_kind", table_name="database_profiles")
    op.drop_index("ix_messages_conv_created", table_name="messages")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_index("ix_databases_visibility", table_name="databases")
    op.drop_index("ix_databases_owner_user_id", table_name="databases")
