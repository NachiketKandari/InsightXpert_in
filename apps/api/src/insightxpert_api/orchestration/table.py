"""SQLAlchemy Core tables for orchestration persistence.

Tables declared here register onto the shared ``db.base.metadata``, so Alembic
autogen sees them via the import in ``alembic/env.py``. Schema matches spec
§4 and the migration ``2026_04_21_0002_orchestration_tables.py``.

All timestamps are unix-seconds integers to match the Phase A convention.
"""

from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String, Table, Text

from ..db.base import metadata

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False),
    Column("db_id", String(255), nullable=True),
    Column("title", String(255), nullable=True),
    Column("is_starred", Integer, nullable=False, server_default="0"),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
)
Index("ix_conversations_user_id", conversations.c.user_id)

messages = Table(
    "messages",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", String(36), nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("chunks_json", Text, nullable=True),
    Column("tokens_in", Integer, nullable=True),
    Column("tokens_out", Integer, nullable=True),
    Column("created_at", Integer, nullable=False),
)
Index("ix_messages_conversation_id", messages.c.conversation_id)

prompt_templates = Table(
    "prompt_templates",
    metadata,
    Column("name", String(128), primary_key=True),
    Column("content", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("is_active", Integer, nullable=False, server_default="1"),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
)

insights = Table(
    "insights",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", String(36), nullable=False),
    Column("content", Text, nullable=False),
    Column("summary", Text, nullable=True),
    Column("created_at", Integer, nullable=False),
)

agent_executions = Table(
    "agent_executions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", String(36), nullable=False),
    Column("message_id", String(36), nullable=True),
    Column("task_id", String(64), nullable=False),
    Column("agent", String(64), nullable=False),
    Column("category", String(64), nullable=True),
    Column("task", Text, nullable=False),
    Column("final_sql", Text, nullable=True),
    Column("final_answer", Text, nullable=True),
    Column("success", Integer, nullable=False),
    Column("error", Text, nullable=True),
    Column("duration_ms", Integer, nullable=False),
    Column("steps_json", Text, nullable=True),
    Column("created_at", Integer, nullable=False),
)

enrichment_traces = Table(
    "enrichment_traces",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("conversation_id", String(36), nullable=False),
    Column("message_id", String(36), nullable=True),
    Column("source_index", Integer, nullable=False),
    Column("category", String(64), nullable=True),
    Column("question", Text, nullable=False),
    Column("rationale", Text, nullable=True),
    Column("final_sql", Text, nullable=True),
    Column("final_answer", Text, nullable=True),
    Column("success", Integer, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("steps_json", Text, nullable=True),
    Column("created_at", Integer, nullable=False),
)
