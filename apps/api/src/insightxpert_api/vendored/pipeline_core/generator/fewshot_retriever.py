"""Retrieve similar few-shot examples for SQL generation prompts."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.profiler.fewshot_builder import mask_question
from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex

logger = logging.getLogger(__name__)


class FewShotRetriever:
    """Retrieve k most similar train Q+SQL pairs via vector similarity."""

    def __init__(self, index: VectorIndex, entries: list[dict], llm: BaseLLM) -> None:
        self._index = index
        self._entries = {str(e["question_id"]): e for e in entries}
        self._llm = llm

    @staticmethod
    def load(index_dir: Path, llm: BaseLLM) -> "FewShotRetriever":
        """Load a pre-built few-shot index from disk."""
        npz_path = index_dir / "fewshot_index.npz"
        ids_path = index_dir / "fewshot_ids.json"
        entries_path = index_dir / "fewshot_entries.json"

        if not npz_path.exists():
            raise FileNotFoundError(
                f"Few-shot index not found at {npz_path}. "
                "Run: python -m insightxpert build-fewshot-index"
            )

        index = VectorIndex.load(npz_path, ids_path)
        entries = json.loads(entries_path.read_text())
        return FewShotRetriever(index, entries, llm)

    def retrieve(
        self,
        question: str,
        k: int = 8,
        exclude_questions: set[str] | None = None,
    ) -> list[dict]:
        """Return top-k similar train examples, excluding exact question matches.

        Each returned dict has: question, sql, db_id, difficulty, question_id.
        """
        masked = mask_question(question)
        embedding = self._llm.embed([masked])
        if not embedding or not embedding[0]:
            logger.warning("Failed to embed question for few-shot retrieval")
            return []

        # Fetch extra results to account for exclusions
        results = self._index.search(embedding[0], top_k=k + 10)

        exclude_norm = {q.strip().lower() for q in (exclude_questions or set())}
        # Always exclude the exact input question
        exclude_norm.add(question.strip().lower())

        examples: list[dict] = []
        for qid_str, score in results:
            if len(examples) >= k:
                break
            entry = self._entries.get(qid_str)
            if not entry:
                continue
            if entry["question"].strip().lower() in exclude_norm:
                logger.debug("Excluding exact match: qid=%s", qid_str)
                continue
            examples.append({
                "question": entry["question"],
                "sql": entry["sql"],
                "db_id": entry["db_id"],
                "difficulty": entry["difficulty"],
                "question_id": entry["question_id"],
                "similarity": score,
            })

        logger.debug(
            "Few-shot: retrieved %d examples (top score=%.3f)",
            len(examples),
            examples[0]["similarity"] if examples else 0.0,
        )
        return examples
