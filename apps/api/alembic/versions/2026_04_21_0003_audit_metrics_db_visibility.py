"""B3 — audit_log, query_metrics, databases, database_shares

Revision ID: 20260421_0003
Revises: 20260421_0002
Create Date: 2026-04-21

Creates the observability persistence foundation (spec §4):
  - audit_log — one row per mutating request
  - query_metrics — one row per chat turn + thumbs
  - databases — visibility + ownership
  - database_shares — explicit per-user grants for shared visibility
Seeds bundled BIRD DBs found on disk as visibility='public', owner NULL.
"""

from __future__ import annotations

import time
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260421_0003"
down_revision: str | None = "20260421_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- audit_log -----------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_audit_log_created_at",
        "audit_log",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_log_user_id_created_at",
        "audit_log",
        ["user_id", sa.text("created_at DESC")],
    )

    # --- query_metrics -------------------------------------------------
    op.create_table(
        "query_metrics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("db_id", sa.String(length=255), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("final_sql", sa.Text(), nullable=True),
        sa.Column("agent_mode", sa.String(length=16), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("thumbs", sa.String(length=8), nullable=True),
        sa.Column("stage_timings_json", sa.Text(), nullable=True),
        sa.Column("agent_trace_summary_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "thumbs IN ('up','down') OR thumbs IS NULL",
            name="query_metrics_thumbs_check",
        ),
    )
    op.create_index(
        "ix_query_metrics_created_at",
        "query_metrics",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_query_metrics_user_id_created_at",
        "query_metrics",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_query_metrics_db_id", "query_metrics", ["db_id"])

    # --- databases + shares --------------------------------------------
    op.create_table(
        "databases",
        sa.Column("db_id", sa.String(length=255), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('private','shared','public')",
            name="databases_visibility_check",
        ),
    )
    op.create_table(
        "database_shares",
        sa.Column("db_id", sa.String(length=255), primary_key=True),
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )

    # --- Seed bundled BIRD DBs as visibility='public' -------------------
    # Databases directory lives at apps/api/Databases (symlinked in dev).
    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    bundled = api_dir / "Databases"
    if bundled.exists() and bundled.is_dir():
        now = int(time.time())
        bind = op.get_bind()
        dbs_tbl = sa.table(
            "databases",
            sa.column("db_id", sa.String),
            sa.column("owner_user_id", sa.String),
            sa.column("visibility", sa.String),
            sa.column("size_bytes", sa.Integer),
            sa.column("created_at", sa.Integer),
        )
        for entry in sorted(bundled.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() != ".sqlite":
                continue
            db_id = entry.stem
            try:
                size_bytes = entry.stat().st_size
            except OSError:
                size_bytes = None
            bind.execute(
                dbs_tbl.insert().values(
                    db_id=db_id,
                    owner_user_id=None,
                    visibility="public",
                    size_bytes=size_bytes,
                    created_at=now,
                )
            )


def downgrade() -> None:
    op.drop_table("database_shares")
    op.drop_table("databases")
    op.drop_index("ix_query_metrics_db_id", table_name="query_metrics")
    op.drop_index("ix_query_metrics_user_id_created_at", table_name="query_metrics")
    op.drop_index("ix_query_metrics_created_at", table_name="query_metrics")
    op.drop_table("query_metrics")
    op.drop_index("ix_audit_log_user_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
