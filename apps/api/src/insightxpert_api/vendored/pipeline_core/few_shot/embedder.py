"""Embed sampled few-shot QA pairs and persist them with their pairs file."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import numpy as np

from insightxpert_api.vendored.pipeline_core.few_shot.sampler import (
    FewShotPair,
    sample_pairs,
    serialize_pairs,
)
from insightxpert_api.vendored.pipeline_core.few_shot.storage import (
    FEW_SHOT_DIR,
    emb_key,
    embeddings_path,
    qa_pairs_path,
)
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM

logger = logging.getLogger(__name__)


async def _embed_pairs(
    pairs: dict[str, list[FewShotPair]], llm: BaseLLM,
) -> dict[str, np.ndarray]:
    """Embed every pair's question; return {db_id: matrix} aligned with pair order.

    Drops any pair whose embedding failed (returns [] sentinel) — both from the
    output matrix and from the in-memory pairs dict (mutated in place) so the
    persisted JSON stays aligned with the persisted matrix.
    """
    embeddings: dict[str, np.ndarray] = {}
    for db_id in sorted(pairs):
        db_pairs = pairs[db_id]
        if not db_pairs:
            continue
        texts = [p.question for p in db_pairs]
        logger.info("db_id=%s: embedding %d questions", db_id, len(texts))
        t0 = time.time()
        raw = await llm.async_embed(texts)
        elapsed = time.time() - t0

        kept_pairs: list[FewShotPair] = []
        kept_vecs: list[list[float]] = []
        dropped = 0
        for pair, vec in zip(db_pairs, raw):
            if vec:
                kept_pairs.append(pair)
                kept_vecs.append(vec)
            else:
                dropped += 1
        if dropped:
            logger.warning("db_id=%s: dropped %d pairs whose embedding failed", db_id, dropped)
        pairs[db_id] = kept_pairs
        if kept_vecs:
            embeddings[db_id] = np.array(kept_vecs, dtype=np.float32)
            logger.info(
                "db_id=%s: embedded %d/%d in %.1fs (dim=%d)",
                db_id, len(kept_vecs), len(texts), elapsed, len(kept_vecs[0]),
            )
    return embeddings


def build_index(
    bird_train_path: Path,
    llm: BaseLLM,
    benchmark: str = "mini_dev",
    per_db: int = 20,
    seed: int = 42,
) -> tuple[Path, Path]:
    """End-to-end build: sample pairs, embed, persist.

    Returns ``(qa_pairs_path, embeddings_path)``. Overwrites any existing files.
    """
    pairs = sample_pairs(
        bird_train_path=bird_train_path,
        benchmark=benchmark,
        per_db=per_db,
        seed=seed,
    )

    t0 = time.time()
    embeddings = asyncio.run(_embed_pairs(pairs, llm))
    logger.info(
        "Embedded all DBs in %.1fs total (input_tokens=%d, output_tokens=%d)",
        time.time() - t0, llm.total_input_tokens, llm.total_output_tokens,
    )

    FEW_SHOT_DIR.mkdir(parents=True, exist_ok=True)
    pairs_out = qa_pairs_path(benchmark)
    pairs_out.write_text(json.dumps(serialize_pairs(pairs), indent=2))
    logger.info("Wrote %d DBs of QA pairs → %s", len(pairs), pairs_out)

    emb_out = embeddings_path(benchmark)
    np.savez(emb_out, **{emb_key(db_id): mat for db_id, mat in embeddings.items()})
    logger.info("Wrote %d embedding matrices → %s", len(embeddings), emb_out)

    total = sum(len(v) for v in pairs.values())
    logger.info(
        "Few-shot build complete: %d pairs across %d DBs (per_db=%d, seed=%d)",
        total, len(pairs), per_db, seed,
    )
    return pairs_out, emb_out
