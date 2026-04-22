"""`query_metrics` table (SQLAlchemy Core).

One row per chat turn, populated by chat route via BackgroundTasks post-stream.
Thumbs are nullable and mutated by the /feedback route.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    Index,
    Integer,
    String,
    Table,
    Text,
)

from ..db.base import metadata

query_metrics = Table(
    "query_metrics",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False),
    Column("conversation_id", String(36), nullable=False),
    Column("db_id", String(255), nullable=True),
    Column("question", Text, nullable=False),
    Column("final_sql", Text, nullable=True),
    Column("agent_mode", String(16), nullable=True),
    Column("tokens_in", Integer, nullable=True),
    Column("tokens_out", Integer, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("thumbs", String(8), nullable=True),
    Column("stage_timings_json", Text, nullable=True),
    Column("agent_trace_summary_json", Text, nullable=True),
    Column("created_at", Integer, nullable=False),
    # Phase 1.2 — spend/quota columns (see alembic 20260425_0001).
    Column("source", String(32), nullable=True),
    Column("provider", String(32), nullable=True),
    Column("model", String(64), nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("pricing_version", String(32), nullable=True),
    Column("source_ref_id", String(255), nullable=True),
    CheckConstraint(
        "thumbs IN ('up','down') OR thumbs IS NULL",
        name="query_metrics_thumbs_check",
    ),
)

Index("ix_query_metrics_created_at", query_metrics.c.created_at.desc())
Index(
    "ix_query_metrics_user_id_created_at",
    query_metrics.c.user_id,
    query_metrics.c.created_at.desc(),
)
Index("ix_query_metrics_db_id", query_metrics.c.db_id)
Index(
    "ix_query_metrics_source_created_at",
    query_metrics.c.source,
    query_metrics.c.created_at.desc(),
)
