"""Seed the ``transactions`` bundled DB row.

Synced from Turso (source of truth) into apps/api/Databases/transactions.sqlite
by scripts/sync-turso-transactions.sh. The B3 migration seeding loop only runs
on the initial schema bootstrap, so this one-off migration is how the new
bundled DB gets a visibility=public row on existing app.db instances.

Idempotent: skips insert if the row already exists. Down-migration removes it.
"""

from __future__ import annotations

import time
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260422_0001"
down_revision: str | None = "20260421_0003"
branch_labels = None
depends_on = None

_DB_ID = "transactions"


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT 1 FROM databases WHERE db_id = :id"),
        {"id": _DB_ID},
    ).scalar()
    if existing:
        return

    # Size is advisory; fall back to None if the file hasn't been synced yet.
    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    sqlite_path = api_dir / "Databases" / f"{_DB_ID}.sqlite"
    try:
        size_bytes = sqlite_path.stat().st_size if sqlite_path.exists() else None
    except OSError:
        size_bytes = None

    bind.execute(
        sa.text(
            "INSERT INTO databases (db_id, owner_user_id, visibility, size_bytes, created_at) "
            "VALUES (:id, NULL, 'public', :size, :now)"
        ),
        {"id": _DB_ID, "size": size_bytes, "now": int(time.time())},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM databases WHERE db_id = :id"),
        {"id": _DB_ID},
    )
