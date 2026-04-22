"""Phase 1.2 — extend query_metrics with cost/source columns.

Adds six columns so every LLM emission site (chat, profile, automation,
trigger_compile) can record spend through a single unified path:

    - source          TEXT (NOT NULL, default 'chat')
    - provider        TEXT — e.g. 'gemini'
    - model           TEXT — e.g. 'gemini-2.5-flash'
    - cost_usd        REAL — computed at write time (pricing registry)
    - pricing_version TEXT — stamp from registry so historic rows stay truthful
    - source_ref_id   TEXT — generalised pointer (db_id | automation_id | convo_id)

Back-fills existing rows with ``source='chat'``, ``provider='gemini'``,
``pricing_version='legacy'`` so dashboards keep working. ``model`` stays NULL
for historic rows (can't be recovered).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0001"
down_revision: str | None = "20260424_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite's ALTER TABLE ADD COLUMN is fine for all of these — no CHECK or
    # FK constraints.  We avoid a CHECK on ``source`` because SQLite would
    # require batch_alter_table and the validation already lives at the
    # application layer (metrics/llm_usage.py Literal type).
    op.add_column(
        "query_metrics",
        sa.Column("source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "query_metrics",
        sa.Column("provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "query_metrics",
        sa.Column("model", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "query_metrics",
        sa.Column("cost_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "query_metrics",
        sa.Column("pricing_version", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "query_metrics",
        sa.Column("source_ref_id", sa.String(length=255), nullable=True),
    )

    # Back-fill existing rows: all historic emissions were chat turns.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE query_metrics SET source = 'chat', provider = 'gemini', "
            "pricing_version = 'legacy' WHERE source IS NULL"
        )
    )

    # Supporting index for "profile spend by user in last 24h" (Phase 1.4
    # per-user daily cap) and "top sources by cost last week" (admin view).
    op.create_index(
        "ix_query_metrics_source_created_at",
        "query_metrics",
        ["source", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_query_metrics_source_created_at", table_name="query_metrics"
    )
    with op.batch_alter_table("query_metrics") as batch:
        batch.drop_column("source_ref_id")
        batch.drop_column("pricing_version")
        batch.drop_column("cost_usd")
        batch.drop_column("model")
        batch.drop_column("provider")
        batch.drop_column("source")
