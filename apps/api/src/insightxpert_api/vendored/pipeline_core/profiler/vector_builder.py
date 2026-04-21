import json
import logging
from pathlib import Path

import numpy as np

from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile

logger = logging.getLogger(__name__)


class VectorIndex:
    """Cosine similarity index over column long-summary embeddings."""

    def __init__(self, embeddings: np.ndarray, column_ids: list[str]):
        self.embeddings = embeddings      # shape: (num_columns, embed_dim)
        self.column_ids = column_ids

    def search(
        self, query_embedding: list[float], top_k: int = 10
    ) -> list[tuple[str, float]]:
        """Return (column_id, similarity) pairs sorted by descending cosine similarity."""
        q = np.array(query_embedding, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-10)
        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-10
        normed = self.embeddings / norms
        scores = normed @ q_norm
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(self.column_ids[i], float(scores[i])) for i in top_indices]

    def save(self, npz_path: Path, cols_path: Path) -> None:
        """Persist embeddings as a .npz file and column IDs as JSON."""
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(npz_path, embeddings=self.embeddings)
        cols_path.write_text(json.dumps(self.column_ids, indent=2))

    @staticmethod
    def load(npz_path: Path, cols_path: Path) -> "VectorIndex":
        """Load embeddings and column IDs from disk to reconstruct a VectorIndex."""
        data = np.load(npz_path)
        embeddings = data["embeddings"]
        column_ids = json.loads(cols_path.read_text())
        return VectorIndex(embeddings=embeddings, column_ids=column_ids)


class VectorBuilder:
    """Builds a VectorIndex by embedding all column long-summaries via the LLM."""

    async def async_build(self, profile: DatabaseProfile, llm: BaseLLM) -> VectorIndex:
        """Embed all column descriptions concurrently.

        Columns whose embeddings fail ([] sentinel from async_embed) are excluded
        from the index with a warning — the remaining columns are indexed normally.
        """
        column_ids: list[str] = []
        texts: list[str] = []

        for table in profile.tables:
            for col in table.columns:
                col_id = f"{table.name}.{col.name}"
                # Build embedding text: prefer quirk semantic_hint for cryptic columns,
                # fall back to long_summary. Always append aliases so semantic search
                # finds user phrases like "average salary" → district.A11.
                base_text = ""
                if col.quirks.semantic_hint:
                    base_text = col.quirks.semantic_hint
                else:
                    base_text = col.long_summary or col.mechanical_description or col_id
                extras: list[str] = []
                if col.quirks.aliases:
                    col_lower = col.name.lower()
                    col_spaced = col_lower.replace("_", " ")
                    useful = [
                        a for a in col.quirks.aliases
                        if a.lower() != col_lower and a.lower() != col_spaced
                    ]
                    if useful:
                        extras.append(f"Also known as: {', '.join(useful)}")
                if col.quirks.enum_labels:
                    extras.append(
                        "Known values: "
                        + ", ".join(
                            f"{k}={v}" for k, v in col.quirks.enum_labels.items()
                            if v and v != "unknown"
                        )
                    )
                text = base_text + (" " + ". ".join(extras) if extras else "")
                column_ids.append(col_id)
                texts.append(text)

        logger.debug("Embedding %d columns for vector index", len(texts))
        raw_embeddings = await llm.async_embed(texts)

        # Filter out columns whose embedding ultimately failed ([] sentinel)
        valid_ids: list[str] = []
        valid_embeddings: list[list[float]] = []
        for col_id, emb in zip(column_ids, raw_embeddings):
            if emb:
                valid_ids.append(col_id)
                valid_embeddings.append(emb)
            else:
                logger.warning(
                    "Column '%s' excluded from vector index — embedding failed", col_id
                )

        skipped = len(column_ids) - len(valid_ids)
        if skipped:
            logger.warning(
                "%d/%d columns excluded from vector index due to embedding failures",
                skipped, len(column_ids),
            )

        if not valid_embeddings:
            logger.error("All embeddings failed — vector index will be empty")
            embeddings = np.empty((0, 0), dtype=np.float32)
        else:
            embeddings = np.array(valid_embeddings, dtype=np.float32)

        logger.debug("Vector index built: shape=%s (%d columns)", embeddings.shape, len(valid_ids))
        return VectorIndex(embeddings=embeddings, column_ids=valid_ids)
