"""Admin-side RAG ops — wraps the vendored ``VectorStore``.

The vendored ``VectorStore.flush_qa_pairs()`` drops + recreates the
``qa_pairs`` ChromaDB collection, leaving DDL / docs / findings intact.
That's exactly the semantic we want for the admin "clear learned QA
pairs" button; we just proxy through it and return the count.

Tests monkeypatch ``clear_qa_pairs`` directly so they don't pay the
cost of spinning up ChromaDB + ONNX embeddings — we only verify the
HTTP surface (auth + status codes).
"""

from __future__ import annotations

import os


def _persist_dir() -> str:
    """Where the vendored store keeps its data. Config-overridable, disk default."""
    return os.environ.get("RAG_PERSIST_DIR", "./chroma_data")


def clear_qa_pairs() -> int:
    """Clear the QA-pairs collection. Returns the number of pairs removed.

    Lazy-imports the vendored store so tests that monkeypatch this symbol
    don't pay ChromaDB's startup cost.
    """
    from ..vendored.agents_core.rag.store import VectorStore

    store = VectorStore(persist_dir=_persist_dir())
    return store.flush_qa_pairs()
