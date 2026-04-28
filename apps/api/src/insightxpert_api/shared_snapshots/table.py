"""SQLAlchemy table declaration for ``shared_snapshots``.

Persistence backing for the chat-share feature. One row per published
snapshot. ``token`` is the capability — unguessable, server-generated,
revocable by setting ``revoked_at``. The full viewable payload lives in
``payload_json`` so the public read path never joins to live tables.
"""

from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String, Table, Text

from ..db.base import metadata


shared_snapshots = Table(
    "shared_snapshots",
    metadata,
    Column("token", String(64), primary_key=True),
    Column("conversation_id", String(36), nullable=False),
    Column("owner_user_id", String(36), nullable=False),
    Column("db_id", String(255), nullable=True),
    Column("db_kind", String(32), nullable=False),
    Column("title", String(255), nullable=True),
    Column("payload_json", Text, nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("expires_at", Integer, nullable=True),
    Column("revoked_at", Integer, nullable=True),
    Column("view_count", Integer, nullable=False, server_default="0"),
)
Index("ix_shared_snapshots_owner_user_id", shared_snapshots.c.owner_user_id)
Index("ix_shared_snapshots_conversation_id", shared_snapshots.c.conversation_id)
