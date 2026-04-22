"""databases: add dialect + connection_url_env_var + seed toxicology_pg.

Adds two columns to ``databases``:

* ``dialect TEXT NOT NULL DEFAULT 'sqlite'`` — backfills all existing rows.
* ``connection_url_env_var TEXT NULL`` — env-var *name* for non-sqlite rows.
  The secret itself is never stored in the DB.

Also seeds one row: ``db_id='toxicology_pg'`` pointing at
``DATABASE_URL_TOXICOLOGY_PG``. Idempotent — skips if already present.
"""
from __future__ import annotations

import time

import sqlalchemy as sa
from alembic import op

revision = "20260425_0002"
down_revision: str | None = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("databases") as b:
        b.add_column(
            sa.Column(
                "dialect",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'sqlite'"),
            )
        )
        b.add_column(
            sa.Column("connection_url_env_var", sa.String(length=255), nullable=True)
        )
        b.create_check_constraint(
            "databases_dialect_check",
            "dialect IN ('sqlite','postgres')",
        )

    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT 1 FROM databases WHERE db_id = 'toxicology_pg'")
    ).first()
    if existing is None:
        dbs = sa.table(
            "databases",
            sa.column("db_id", sa.String),
            sa.column("owner_user_id", sa.String),
            sa.column("visibility", sa.String),
            sa.column("size_bytes", sa.Integer),
            sa.column("created_at", sa.Integer),
            sa.column("dialect", sa.String),
            sa.column("connection_url_env_var", sa.String),
        )
        op.bulk_insert(
            dbs,
            [
                {
                    "db_id": "toxicology_pg",
                    "owner_user_id": None,
                    "visibility": "public",
                    "size_bytes": None,
                    "created_at": int(time.time()),
                    "dialect": "postgres",
                    "connection_url_env_var": "DATABASE_URL_TOXICOLOGY_PG",
                }
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM databases WHERE db_id = 'toxicology_pg'"))
    with op.batch_alter_table("databases") as b:
        b.drop_constraint("databases_dialect_check", type_="check")
        b.drop_column("connection_url_env_var")
        b.drop_column("dialect")
