"""Unit tests for :mod:`insightxpert_api.rag.pgvector_store`.

Uses the SQLite ``fresh_db`` fixture as a stand-in for Postgres so we can
verify the round-trip + cosine ranking without a live pgvector cluster.
The ``embedding`` column on SQLite is ``LargeBinary`` (packed float32 bytes)
and similarity is computed in Python — slow but exact.
"""

from __future__ import annotations

import pytest

from insightxpert_api.rag.pgvector_store import PgvectorStore


@pytest.fixture()
def store(fresh_db):  # noqa: ARG001 — fixture sets up the metadata engine
    return PgvectorStore()


def test_add_and_count_round_trip(store: PgvectorStore) -> None:
    store.add(
        collection="qa_pairs",
        documents=["What is 2+2?"],
        embeddings=[[1.0, 0.0, 0.0]],
        metadatas=[{"sql": "SELECT 4"}],
    )
    assert store.count("qa_pairs") == 1
    assert store.count("ddl") == 0


def test_add_is_idempotent_on_repeat(store: PgvectorStore) -> None:
    """Same content -> same id -> upsert (no duplicate row)."""
    for _ in range(3):
        store.add(
            collection="docs",
            documents=["constant text"],
            embeddings=[[0.1, 0.2, 0.3]],
        )
    assert store.count("docs") == 1


def test_query_orders_by_cosine_distance(store: PgvectorStore) -> None:
    # Three orthogonal-ish vectors, query closest to the first.
    store.add(
        collection="qa_pairs",
        documents=["near", "far", "middle"],
        embeddings=[
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.7, 0.7, 0.0],
        ],
        ids=["near", "far", "middle"],
    )
    hits = store.query("qa_pairs", [1.0, 0.0, 0.0], top_k=3)
    assert [h["id"] for h in hits] == ["near", "middle", "far"]
    # Distances must be monotonic non-decreasing.
    assert hits[0]["distance"] <= hits[1]["distance"] <= hits[2]["distance"]
    # The exact-match query has distance ~0.
    assert hits[0]["distance"] == pytest.approx(0.0, abs=1e-6)


def test_query_respects_top_k_and_collection(store: PgvectorStore) -> None:
    store.add(
        collection="ddl",
        documents=["d1", "d2"],
        embeddings=[[1.0, 0.0], [0.9, 0.1]],
        ids=["d1", "d2"],
    )
    store.add(
        collection="qa_pairs",
        documents=["q1"],
        embeddings=[[1.0, 0.0]],
        ids=["q1"],
    )
    ddl_hits = store.query("ddl", [1.0, 0.0], top_k=1)
    assert len(ddl_hits) == 1
    # Cross-collection isolation: querying ddl never returns qa_pairs.
    assert all(h["id"] != "q1" for h in store.query("ddl", [1.0, 0.0], top_k=10))


def test_filter_by_metadata_exact_match(store: PgvectorStore) -> None:
    store.add(
        collection="qa_pairs",
        documents=["a", "b"],
        embeddings=[[1.0, 0.0], [0.99, 0.0]],
        metadatas=[{"sql_valid": True}, {"sql_valid": False}],
        ids=["a", "b"],
    )
    only_valid = store.query(
        "qa_pairs", [1.0, 0.0], top_k=10, filter={"sql_valid": True}
    )
    assert {h["id"] for h in only_valid} == {"a"}


def test_db_id_scoping(store: PgvectorStore) -> None:
    store.add(
        collection="docs",
        documents=["x", "y"],
        embeddings=[[1.0, 0.0], [1.0, 0.0]],
        ids=["x", "y"],
        db_id="db1",
    )
    store.add(
        collection="docs",
        documents=["z"],
        embeddings=[[1.0, 0.0]],
        ids=["z"],
        db_id="db2",
    )
    assert store.count("docs", db_id="db1") == 2
    assert store.count("docs", db_id="db2") == 1
    hits = store.query("docs", [1.0, 0.0], top_k=10, db_id="db2")
    assert {h["id"] for h in hits} == {"z"}


def test_flush_collection_removes_only_that_collection(store: PgvectorStore) -> None:
    store.add(collection="qa_pairs", documents=["q"], embeddings=[[1.0]])
    store.add(collection="ddl", documents=["d"], embeddings=[[1.0]])
    removed = store.flush("qa_pairs")
    assert removed == 1
    assert store.count("qa_pairs") == 0
    assert store.count("ddl") == 1


def test_flush_qa_pairs_compat_shim(store: PgvectorStore) -> None:
    store.add(collection="qa_pairs", documents=["q"], embeddings=[[0.1]])
    assert store.flush_qa_pairs() == 1
    assert store.flush_qa_pairs() == 0


def test_metadata_round_trips_as_dict(store: PgvectorStore) -> None:
    store.add(
        collection="qa_pairs",
        documents=["hello"],
        embeddings=[[1.0]],
        metadatas=[{"nested": {"k": 1}, "tag": "x"}],
        ids=["hello"],
    )
    hits = store.query("qa_pairs", [1.0], top_k=1)
    assert hits[0]["metadata"]["tag"] == "x"
    assert hits[0]["metadata"]["nested"] == {"k": 1}


def test_admin_clear_qa_pairs_uses_store(fresh_db) -> None:  # noqa: ARG001
    """``rag.admin_service.clear_qa_pairs`` flushes the qa_pairs collection."""
    from insightxpert_api.rag import admin_service

    PgvectorStore().add(
        collection="qa_pairs",
        documents=["q1", "q2"],
        embeddings=[[1.0], [0.5]],
    )
    PgvectorStore().add(
        collection="ddl",
        documents=["create table t (id int)"],
        embeddings=[[1.0]],
    )

    removed = admin_service.clear_qa_pairs()
    assert removed == 2
    assert PgvectorStore().count("qa_pairs") == 0
    # DDL untouched.
    assert PgvectorStore().count("ddl") == 1
