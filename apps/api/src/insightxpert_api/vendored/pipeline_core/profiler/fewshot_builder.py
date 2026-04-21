"""Build a vector index over BIRD train questions for few-shot example retrieval."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import numpy as np

from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex

logger = logging.getLogger(__name__)

# Replace quoted string literals with <VALUE> so similarity is structural
_QUOTED_RE = re.compile(r"""(['"])(.*?)\1""")


def mask_question(question: str) -> str:
    """Replace quoted literals in a question with <VALUE> placeholders."""
    return _QUOTED_RE.sub("<VALUE>", question)


def build_fewshot_index(
    train_path: Path,
    llm: BaseLLM,
    output_dir: Path,
) -> tuple[VectorIndex, list[dict]]:
    """Load train entries, embed masked questions, save index + entries.

    Returns the built (VectorIndex, entries list).
    """
    with open(train_path) as f:
        raw_entries: list[dict] = json.load(f)
    logger.info("Loaded %d train entries from %s", len(raw_entries), train_path)

    entries: list[dict] = []
    texts: list[str] = []
    for e in raw_entries:
        masked = mask_question(e["question"])
        entries.append({
            "question_id": e["question_id"],
            "db_id": e["db_id"],
            "question": e["question"],
            "masked_question": masked,
            "sql": e["SQL"],
            "difficulty": e.get("difficulty", ""),
        })
        texts.append(masked)

    logger.info("Embedding %d masked questions...", len(texts))
    raw_embeddings = asyncio.run(llm.async_embed(texts))

    valid_entries: list[dict] = []
    valid_embeddings: list[list[float]] = []
    for entry, emb in zip(entries, raw_embeddings):
        if emb:
            valid_entries.append(entry)
            valid_embeddings.append(emb)
        else:
            logger.warning(
                "Question %d excluded — embedding failed", entry["question_id"]
            )

    skipped = len(entries) - len(valid_entries)
    if skipped:
        logger.warning("%d/%d entries excluded due to embedding failures", skipped, len(entries))

    embeddings_array = np.array(valid_embeddings, dtype=np.float32) if valid_embeddings else np.empty((0, 0), dtype=np.float32)
    column_ids = [str(e["question_id"]) for e in valid_entries]
    index = VectorIndex(embeddings=embeddings_array, column_ids=column_ids)

    output_dir.mkdir(parents=True, exist_ok=True)
    npz_path = output_dir / "fewshot_index.npz"
    cols_path = output_dir / "fewshot_ids.json"
    entries_path = output_dir / "fewshot_entries.json"

    index.save(npz_path, cols_path)
    entries_path.write_text(json.dumps(valid_entries, indent=2))

    logger.info(
        "Few-shot index saved: %d entries, embeddings shape=%s → %s",
        len(valid_entries), embeddings_array.shape, output_dir,
    )
    return index, valid_entries
