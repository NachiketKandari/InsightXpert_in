"""Admin-side RAG ops — backed by pgvector on the metadata DB.

Replaces the on-disk ChromaDB store. ``clear_qa_pairs()`` now deletes
``WHERE collection = 'qa_pairs'`` from the ``vectors`` table.

Tests monkeypatch ``clear_qa_pairs`` directly when they only care about
the HTTP surface (auth + status codes); see ``tests/`` for the integration
case that exercises the real store against ``fresh_db``.
"""

from __future__ import annotations


def clear_qa_pairs() -> int:
    """Clear the QA-pairs collection. Returns the number of pairs removed.

    Lazy-imports the store so unrelated tests don't pay any DB cost.
    """
    from .pgvector_store import PgvectorStore

    return PgvectorStore().flush("qa_pairs")
