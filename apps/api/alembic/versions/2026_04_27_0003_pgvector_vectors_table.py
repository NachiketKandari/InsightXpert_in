"""Phase 1.x — pgvector migration: enable extension + create ``vectors`` table.

Replaces the on-disk ChromaDB store with a Postgres-native pgvector table
that lives next to the metadata DB on Supabase. Stays a no-op of the
extension on SQLite (used by unit tests) — the embedding column there
is ``LargeBinary`` so we can store packed float32 vectors and run
exact-match cosine similarity in Python (slow but correct for tests).

Dimension comes from the configured Gemini embedding model
(``gemini-embedding-001`` default = 3072).
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "20260427_0003"
down_revision: str | None = "20260425_0001"
branch_labels = None
depends_on = None


def _embedding_dim() -> int:
    """Resolve the embedding dimension at migration-time.

    Defaults to 3072 (Gemini ``gemini-embedding-001`` native size). Overridable
    via ``RAG_EMBEDDING_DIM`` env so deployments that pin a smaller dim
    (e.g. 768/1536) can shrink the column.
    """
    raw = os.environ.get("RAG_EMBEDDING_DIM", "3072")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 3072
    return max(1, n)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    dim = _embedding_dim()

    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.sqlalchemy import Vector

        embedding_col = sa.Column("embedding", Vector(dim), nullable=True)
        metadata_col = sa.Column(
            "metadata_json",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        )
    else:
        embedding_col = sa.Column("embedding", sa.LargeBinary(), nullable=True)
        metadata_col = sa.Column("metadata_json", sa.JSON(), nullable=True)

    op.create_table(
        "vectors",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("collection", sa.String(length=64), nullable=False),
        sa.Column("db_id", sa.String(length=255), nullable=True),
        sa.Column("document", sa.Text(), nullable=False),
        metadata_col,
        embedding_col,
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    op.create_index("ix_vectors_collection_db_id", "vectors", ["collection", "db_id"])
    op.create_index("ix_vectors_collection", "vectors", ["collection"])

    # IVFFlat ANN index — Postgres only, best-effort. Skipped if pgvector
    # version is too old or table is empty (IVFFlat needs data to train).
    # We create it now so it exists; pgvector accepts an empty index and
    # will populate as rows arrive (queries fall back to seq scan until
    # the index is meaningful).
    if dialect == "postgresql":
        try:
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_vectors_embedding_cosine "
                "ON vectors USING ivfflat (embedding vector_cosine_ops) "
                "WITH (lists = 100)"
            )
        except Exception:  # pragma: no cover — older pgvector or empty table
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_vectors_embedding_cosine")
    op.drop_index("ix_vectors_collection", table_name="vectors")
    op.drop_index("ix_vectors_collection_db_id", table_name="vectors")
    op.drop_table("vectors")
    # Intentionally leave the ``vector`` extension installed — other things
    # may depend on it, and it's idempotent on re-up.
