"""pgvector-backed VectorStore replacement.

Implements a small surface that mirrors the parts of the vendored
``VectorStore`` we actually use today (admin ``flush_qa_pairs`` + the
generic ``add`` / ``query`` / ``flush`` shape we want callers to migrate
to). Uses SQLAlchemy directly against the metadata engine.

On Postgres, similarity is computed by pgvector's cosine operator
(``embedding <=> :q``, smaller = closer). On SQLite (unit tests only)
we store packed float32 bytes and rank in Python — slow but exact.
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
from typing import Any, Iterable

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from ..db.engine import get_engine


def _make_id(text_: str) -> str:
    """Deterministic doc id — first 16 hex chars of SHA-256(content)."""
    return hashlib.sha256(text_.encode()).hexdigest()[:16]


def _pack_floats(values: Iterable[float]) -> bytes:
    """Pack a vector into little-endian float32 bytes (SQLite path)."""
    arr = list(values)
    return struct.pack(f"<{len(arr)}f", *arr)


def _unpack_floats(blob: bytes | memoryview | None) -> list[float]:
    if not blob:
        return []
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob[: n * 4]))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine *distance* (1 - cos_sim). Matches pgvector's <=> operator."""
    if not a or not b:
        return 1.0
    n = min(len(a), len(b))
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = a[i]
        y = b[i]
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 1.0
    sim = dot / ((na**0.5) * (nb**0.5))
    return 1.0 - sim


class PgvectorStore:
    """Thin store over the ``vectors`` table.

    Public surface (intentionally narrow — callers migrate as they go):

      add(collection, documents, embeddings, metadatas, ids=None, db_id=None)
      query(collection, query_embedding, top_k=5, db_id=None, filter=None)
      flush(collection, db_id=None)
      count(collection, db_id=None)
    """

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()
        self._is_postgres = self._engine.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def add(
        self,
        collection: str,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
        db_id: str | None = None,
    ) -> list[str]:
        if len(documents) != len(embeddings):
            raise ValueError("documents and embeddings must be the same length")
        metas = metadatas or [{} for _ in documents]
        if len(metas) != len(documents):
            raise ValueError("metadatas length mismatch")
        if ids is None:
            ids = [_make_id(d) for d in documents]
        elif len(ids) != len(documents):
            raise ValueError("ids length mismatch")

        now = int(time.time())
        with self._engine.begin() as conn:
            for doc_id, doc, emb, meta in zip(ids, documents, embeddings, metas):
                self._upsert(conn, doc_id, collection, db_id, doc, meta, emb, now)
        return ids

    def _upsert(
        self,
        conn: Connection,
        doc_id: str,
        collection: str,
        db_id: str | None,
        document: str,
        metadata: dict[str, Any],
        embedding: list[float],
        ts: int,
    ) -> None:
        if self._is_postgres:
            # pgvector's SQLAlchemy helper accepts a list[float] directly when
            # the column is ``Vector``; for parameterised text we cast.
            conn.execute(
                text(
                    """
                    INSERT INTO vectors (id, collection, db_id, document, metadata_json, embedding, created_at)
                    VALUES (:id, :collection, :db_id, :document, CAST(:metadata AS JSONB), CAST(:embedding AS vector), :created_at)
                    ON CONFLICT (id) DO UPDATE SET
                        collection = EXCLUDED.collection,
                        db_id = EXCLUDED.db_id,
                        document = EXCLUDED.document,
                        metadata_json = EXCLUDED.metadata_json,
                        embedding = EXCLUDED.embedding,
                        created_at = EXCLUDED.created_at
                    """
                ),
                {
                    "id": doc_id,
                    "collection": collection,
                    "db_id": db_id,
                    "document": document,
                    "metadata": json.dumps(metadata or {}),
                    "embedding": _to_pgvector_literal(embedding),
                    "created_at": ts,
                },
            )
        else:
            # SQLite: simple delete-then-insert idempotency.
            conn.execute(text("DELETE FROM vectors WHERE id = :id"), {"id": doc_id})
            conn.execute(
                text(
                    """
                    INSERT INTO vectors
                        (id, collection, db_id, document, metadata_json, embedding, created_at)
                    VALUES
                        (:id, :collection, :db_id, :document, :metadata, :embedding, :created_at)
                    """
                ),
                {
                    "id": doc_id,
                    "collection": collection,
                    "db_id": db_id,
                    "document": document,
                    "metadata": json.dumps(metadata or {}),
                    "embedding": _pack_floats(embedding),
                    "created_at": ts,
                },
            )

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def query(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
        db_id: str | None = None,
        filter: dict[str, Any] | None = None,  # noqa: A002 — matches Chroma signature
    ) -> list[dict[str, Any]]:
        """Return up to ``top_k`` rows ordered by cosine distance ASC.

        Each result is ``{"id", "document", "metadata", "distance"}``.
        ``filter`` does an exact-match check against keys in metadata_json
        (Postgres uses ``->>`` operators, SQLite filters in Python).
        """
        if self._is_postgres:
            return self._query_postgres(collection, query_embedding, top_k, db_id, filter)
        return self._query_sqlite(collection, query_embedding, top_k, db_id, filter)

    def _query_postgres(
        self,
        collection: str,
        q_emb: list[float],
        top_k: int,
        db_id: str | None,
        filt: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        clauses = ["collection = :collection"]
        params: dict[str, Any] = {
            "collection": collection,
            "q": _to_pgvector_literal(q_emb),
            "limit": int(top_k),
        }
        if db_id is not None:
            clauses.append("db_id = :db_id")
            params["db_id"] = db_id
        if filt:
            for i, (k, v) in enumerate(filt.items()):
                clauses.append(f"metadata_json ->> :fk{i} = :fv{i}")
                params[f"fk{i}"] = k
                params[f"fv{i}"] = str(v)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT id, document, metadata_json, "
            f"(embedding <=> CAST(:q AS vector)) AS distance "
            f"FROM vectors WHERE {where} "
            f"ORDER BY embedding <=> CAST(:q AS vector) ASC LIMIT :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return [
            {
                "id": r[0],
                "document": r[1],
                "metadata": _coerce_meta(r[2]),
                "distance": float(r[3]),
            }
            for r in rows
        ]

    def _query_sqlite(
        self,
        collection: str,
        q_emb: list[float],
        top_k: int,
        db_id: str | None,
        filt: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        clauses = ["collection = :collection"]
        params: dict[str, Any] = {"collection": collection}
        if db_id is not None:
            clauses.append("db_id = :db_id")
            params["db_id"] = db_id
        where = " AND ".join(clauses)
        sql = (
            "SELECT id, document, metadata_json, embedding "
            f"FROM vectors WHERE {where}"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        scored: list[dict[str, Any]] = []
        for r in rows:
            meta = _coerce_meta(r[2])
            if filt and not all(str(meta.get(k)) == str(v) for k, v in filt.items()):
                continue
            emb = _unpack_floats(r[3])
            scored.append(
                {
                    "id": r[0],
                    "document": r[1],
                    "metadata": meta,
                    "distance": _cosine(q_emb, emb),
                }
            )
        scored.sort(key=lambda x: x["distance"])
        return scored[: int(top_k)]

    # ------------------------------------------------------------------
    # admin
    # ------------------------------------------------------------------

    def flush(self, collection: str, db_id: str | None = None) -> int:
        clauses = ["collection = :collection"]
        params: dict[str, Any] = {"collection": collection}
        if db_id is not None:
            clauses.append("db_id = :db_id")
            params["db_id"] = db_id
        where = " AND ".join(clauses)
        with self._engine.begin() as conn:
            n = conn.execute(
                text(f"SELECT COUNT(*) FROM vectors WHERE {where}"), params
            ).scalar_one()
            conn.execute(text(f"DELETE FROM vectors WHERE {where}"), params)
        return int(n or 0)

    def count(self, collection: str, db_id: str | None = None) -> int:
        clauses = ["collection = :collection"]
        params: dict[str, Any] = {"collection": collection}
        if db_id is not None:
            clauses.append("db_id = :db_id")
            params["db_id"] = db_id
        where = " AND ".join(clauses)
        with self._engine.connect() as conn:
            n = conn.execute(
                text(f"SELECT COUNT(*) FROM vectors WHERE {where}"), params
            ).scalar_one()
        return int(n or 0)

    # ------------------------------------------------------------------
    # admin compatibility shim: vendored ``VectorStore.flush_qa_pairs()``
    # ------------------------------------------------------------------

    def flush_qa_pairs(self) -> int:
        return self.flush("qa_pairs")


def _to_pgvector_literal(values: list[float]) -> str:
    """Render a vector as the literal text pgvector accepts: ``[0.1,0.2,...]``."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _coerce_meta(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray, memoryview)):
        raw = bytes(raw).decode("utf-8")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
