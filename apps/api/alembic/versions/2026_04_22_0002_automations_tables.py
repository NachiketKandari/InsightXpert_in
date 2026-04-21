"""Phase C1 — automations tables.

Tables: automations, automation_triggers, automation_runs, trigger_templates,
notifications. All single-tenant; org_id intentionally absent.
``workflow_graph_json`` on automations reserved for Phase C2 (workflow canvas);
C1 routes accept/return it as pass-through bytes but never interpret it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260422_0002"
down_revision: str | None = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("nl_query", sa.Text(), nullable=False),
        sa.Column("sql_queries_json", sa.Text(), nullable=False),
        sa.Column("db_id", sa.String(length=255), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=True),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_graph_json", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_auto_owner_active", "automations", ["owner_user_id", "is_active"])
    op.create_index("ix_auto_next_run", "automations", ["next_run_at", "is_active"])
    op.create_index("ix_auto_db_id", "automations", ["db_id"])

    op.create_table(
        "automation_triggers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("automation_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("column", sa.String(length=100), nullable=True),
        sa.Column("operator", sa.String(length=10), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("change_percent", sa.Float(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=True),
        sa.Column("nl_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["automations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "type IN ('threshold','row_count','change_detection','column_expression')",
            name="trigger_type_check",
        ),
        sa.CheckConstraint(
            "operator IS NULL OR operator IN ('gt','gte','lt','lte','eq','ne')",
            name="trigger_op_check",
        ),
        sa.CheckConstraint(
            "scope IS NULL OR scope IN ('any_row','all_rows')",
            name="trigger_scope_check",
        ),
    )
    op.create_index("ix_trig_auto_ord", "automation_triggers", ["automation_id", "ordinal"])

    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("automation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("triggers_fired_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["automations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('success','error','skipped','no_trigger')",
            name="run_status_check",
        ),
    )
    op.create_index("ix_run_auto_ts", "automation_runs", ["automation_id", "created_at"])
    op.create_index("ix_run_ts", "automation_runs", ["created_at"])

    op.create_table(
        "trigger_templates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("conditions_json", sa.Text(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tpl_owner", "trigger_templates", ["owner_user_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("automation_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["automations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["automation_runs.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "severity IN ('info','success','warning','error')",
            name="notif_severity_check",
        ),
    )
    op.create_index(
        "ix_notif_user_unread_ts",
        "notifications",
        ["user_id", "is_read", "created_at"],
    )
    op.create_index("ix_notif_auto", "notifications", ["automation_id"])


def downgrade() -> None:
    op.drop_index("ix_notif_auto", table_name="notifications")
    op.drop_index("ix_notif_user_unread_ts", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_tpl_owner", table_name="trigger_templates")
    op.drop_table("trigger_templates")
    op.drop_index("ix_run_ts", table_name="automation_runs")
    op.drop_index("ix_run_auto_ts", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_trig_auto_ord", table_name="automation_triggers")
    op.drop_table("automation_triggers")
    op.drop_index("ix_auto_db_id", table_name="automations")
    op.drop_index("ix_auto_next_run", table_name="automations")
    op.drop_index("ix_auto_owner_active", table_name="automations")
    op.drop_table("automations")
