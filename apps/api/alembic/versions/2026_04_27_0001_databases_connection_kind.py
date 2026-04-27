"""BYO-DB — kind + connection_config_encrypted columns on databases.

Revision ID: 20260427_0001
Revises: 20260425_0001

Adds two columns used by the BYO external DB connector:

    - kind: 'sqlite_file' (default — bundled / uploaded SQLite),
            'libsql', 'sqlite_external', 'postgres'.
    - connection_config_encrypted: Fernet-encrypted JSON blob holding the
      backend-specific connection config (DSN bits + creds). NULL for
      sqlite_file rows where the path is implicit (bundled / object-store).

The Turso libSQL Cutover plan (2026_04_27 turso) is NOT being executed
concurrently; if/when it lands it can backfill rows with `kind='libsql'`
on its own. We do not touch turso_url here because that column does not
yet exist.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260427_0001"
down_revision: str | None = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "databases",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="sqlite_file",
        ),
    )
    op.add_column(
        "databases",
        sa.Column(
            "connection_config_encrypted",
            sa.Text(),
            nullable=True,
        ),
    )
    # Existing rows are bundled SQLite or uploaded SQLite — both map to the
    # 'sqlite_file' default applied above. No backfill needed.


def downgrade() -> None:
    op.drop_column("databases", "connection_config_encrypted")
    op.drop_column("databases", "kind")
