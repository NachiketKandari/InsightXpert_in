"""Top-1 cosine retrieval over per-db few-shot QA pairs."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from insightxpert_api.vendored.pipeline_core.few_shot.sampler import FewShotPair, deserialize_pairs
from insightxpert_api.vendored.pipeline_core.few_shot.storage import (
    db_id_from_key,
    embeddings_path,
    qa_pairs_path,
)
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class FewShotExample(BaseModel):
    """The single retrieved example exposed to the rest of the pipeline."""

    question: str
    gold_sql: str
    columns: list[tuple[str, str]] = []
    similarity: float = 0.0


class FewShotRetriever:
    """Per-DB top-1 retrieval over precomputed BIRD train embeddings."""

    def __init__(
        self,
        pairs: dict[str, list[FewShotPair]],
        embeddings: dict[str, np.ndarray],
        llm: BaseLLM,
    ) -> None:
        self._pairs = pairs
        # Pre-normalize for cosine similarity at runtime.
        self._normed: dict[str, np.ndarray] = {}
        for db_id, mat in embeddings.items():
            if mat.size == 0:
                continue
            norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10
            self._normed[db_id] = (mat / norms).astype(np.float32)
        self._llm = llm
        loaded = sum(len(v) for v in pairs.values())
        logger.info(
            "FewShotRetriever ready: %d DBs (%d pairs total)",
            len(self._normed), loaded,
        )

    @classmethod
    def load(cls, llm: BaseLLM, benchmark: str = "mini_dev") -> "FewShotRetriever | None":
        """Load the persisted index from disk; return None if either file is missing."""
        pairs_path = qa_pairs_path(benchmark)
        emb_path = embeddings_path(benchmark)
        if not pairs_path.exists() or not emb_path.exists():
            logger.error(
                "Few-shot index missing (pairs=%s emb=%s exists=%s/%s). "
                "Build it with: python -m insightxpert build-few-shot --bird-train PATH --benchmark %s",
                pairs_path, emb_path, pairs_path.exists(), emb_path.exists(), benchmark,
            )
            return None
        with pairs_path.open() as f:
            pairs = deserialize_pairs(json.load(f))
        npz = np.load(emb_path)
        embeddings = {db_id_from_key(k): npz[k] for k in npz.files}
        return cls(pairs=pairs, embeddings=embeddings, llm=llm)

    def retrieve(self, db_id: str, question: str) -> FewShotExample | None:
        """Return the single most similar pair for ``db_id`` (cosine top-1)."""
        if db_id not in self._normed:
            logger.debug("Few-shot: no pairs for db_id=%s", db_id)
            return None
        try:
            raw = self._llm.embed([question])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Few-shot: embedding failed for db_id=%s: %s", db_id, exc)
            return None
        if not raw or not raw[0]:
            logger.warning("Few-shot: empty embedding returned for db_id=%s", db_id)
            return None

        q = np.array(raw[0], dtype=np.float32)
        q = q / (np.linalg.norm(q) + 1e-10)
        scores = self._normed[db_id] @ q
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        pair = self._pairs[db_id][best_idx]
        logger.info(
            "few-shot retrieved: db=%s sim=%.3f cols=%d question=%.60s",
            db_id, best_score, len(pair.columns), pair.question,
        )
        return FewShotExample(
            question=pair.question,
            gold_sql=pair.gold_sql,
            columns=list(pair.columns),
            similarity=best_score,
        )
