"""SQLAlchemy Core tables for Phase C1 — automations.

Schema lives in :mod:`insightxpert_api.automations` and is seeded by
``alembic/versions/2026_04_22_0002_automations_tables.py``. This module is the
source of truth for column definitions used by the repository layer.

Design notes:
    * Single-tenant — no ``org_id``. Scope is owner-or-admin only.
    * ``workflow_graph_json`` is a Phase C2 reservation. C1 code never reads or
      writes it; routes accept it as pass-through bytes on create/update.
    * Triggers are normalized into ``automation_triggers`` for querying, but
      the evaluator consumes the denormalized list stored in-memory per run.
    * ``notifications.is_read`` is the only read-state — no separate
      ``notification_dismissals`` table.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
)

from ..db.base import metadata

automations = Table(
    "automations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("description", Text, nullable=True),
    Column("nl_query", Text, nullable=False),
    Column("sql_queries_json", Text, nullable=False),
    Column("db_id", String(255), nullable=False),
    Column("cron_expression", String(100), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="1"),
    Column("owner_user_id", String(36), nullable=False),
    Column("source_conversation_id", String(36), nullable=True),
    Column("source_message_id", String(36), nullable=True),
    Column("workflow_graph_json", Text, nullable=True),
    Column("last_run_at", Integer, nullable=True),
    Column("next_run_at", Integer, nullable=True),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    Index("ix_auto_owner_active", "owner_user_id", "is_active"),
    Index("ix_auto_next_run", "next_run_at", "is_active"),
    Index("ix_auto_db_id", "db_id"),
)

automation_triggers = Table(
    "automation_triggers",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("automation_id", String(36), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("type", String(30), nullable=False),
    Column("column", String(100), nullable=True),
    Column("operator", String(10), nullable=True),
    Column("value", Float, nullable=True),
    Column("change_percent", Float, nullable=True),
    Column("scope", String(20), nullable=True),
    Column("nl_text", Text, nullable=True),
    ForeignKeyConstraint(
        ["automation_id"], ["automations.id"], ondelete="CASCADE"
    ),
    CheckConstraint(
        "type IN ('threshold','row_count','change_detection','column_expression')",
        name="trigger_type_check",
    ),
    CheckConstraint(
        "operator IS NULL OR operator IN ('gt','gte','lt','lte','eq','ne')",
        name="trigger_op_check",
    ),
    CheckConstraint(
        "scope IS NULL OR scope IN ('any_row','all_rows')",
        name="trigger_scope_check",
    ),
    Index("ix_trig_auto_ord", "automation_id", "ordinal"),
)

automation_runs = Table(
    "automation_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("automation_id", String(36), nullable=False),
    Column("status", String(20), nullable=False),
    Column("result_json", Text, nullable=True),
    Column("row_count", Integer, nullable=True),
    Column("execution_time_ms", Integer, nullable=True),
    Column("triggers_fired_json", Text, nullable=True),
    Column("error_message", Text, nullable=True),
    Column("created_at", Integer, nullable=False),
    ForeignKeyConstraint(
        ["automation_id"], ["automations.id"], ondelete="CASCADE"
    ),
    CheckConstraint(
        "status IN ('success','error','skipped','no_trigger')",
        name="run_status_check",
    ),
    Index("ix_run_auto_ts", "automation_id", "created_at"),
    Index("ix_run_ts", "created_at"),
)

trigger_templates = Table(
    "trigger_templates",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("description", Text, nullable=True),
    Column("conditions_json", Text, nullable=False),
    Column("owner_user_id", String(36), nullable=False),
    Column("created_at", Integer, nullable=False),
    Column("updated_at", Integer, nullable=False),
    ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    Index("ix_tpl_owner", "owner_user_id"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False),
    Column("automation_id", String(36), nullable=True),
    Column("run_id", String(36), nullable=True),
    Column("title", String(200), nullable=False),
    Column("message", Text, nullable=False),
    Column("severity", String(20), nullable=False),
    Column("is_read", Boolean, nullable=False, server_default="0"),
    Column("created_at", Integer, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["automation_id"], ["automations.id"], ondelete="SET NULL"
    ),
    ForeignKeyConstraint(
        ["run_id"], ["automation_runs.id"], ondelete="SET NULL"
    ),
    CheckConstraint(
        "severity IN ('info','success','warning','error')",
        name="notif_severity_check",
    ),
    Index("ix_notif_user_unread_ts", "user_id", "is_read", "created_at"),
    Index("ix_notif_auto", "automation_id"),
)

__all__ = [
    "automations",
    "automation_triggers",
    "automation_runs",
    "trigger_templates",
    "notifications",
]
