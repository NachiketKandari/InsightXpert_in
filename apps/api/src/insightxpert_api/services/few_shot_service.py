"""Per-DB question-similarity few-shot retrieval (v1).

This service holds an in-memory bank of BIRD-train QA pairs (per ``db_id``)
and a matrix of pre-computed question embeddings. At chat time it embeds the
user's question and returns the cosine top-1 pair for the active database.

Disk layout (resolved relative to ``apps/api``):

    few_shot/few_shot_<benchmark>.json   — pairs dict (db_id -> [pair, ...])
    few_shot/few_shot_<benchmark>.npz    — per-db emb matrix, key emb__<db_id>

Both files are committed alongside the API code. Embeddings are stored as
``float16`` and truncated to the leading ``EMBEDDING_DIM`` dimensions so that
the bank fits comfortably under the 1 MB ceiling. ``gemini-embedding-001``
is a Matryoshka model — the leading prefix of each vector is meaningful on
its own — so retrieval-time embeddings are sliced + L2-normalized to the
same dimensionality before the cosine match.

Failures are intentionally swallowed: the retriever is best-effort, and a
missing bank or embedding error must NEVER fail a chat turn. Callers
treat ``None`` as "no example" and the SQL-gen prompt's ``{% if
few_shot_example %}`` block is simply skipped.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from pydantic import BaseModel

from ..logging import get_logger

if TYPE_CHECKING:
    from ..llm.gemini import GeminiLLM


log = get_logger("services.few_shot")

# Stored embeddings were L2-normalized after truncation, so retrieval just
# needs to slice the live embedding to the same dim and re-normalize before
# the dot product yields cosine similarity.
EMBEDDING_DIM = 1536

# Resolve the on-disk bank relative to the API package root (apps/api).
# ``__file__`` is at apps/api/src/insightxpert_api/services/few_shot_service.py;
# parents[3] is apps/api/.
_API_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BENCHMARK = "mini_dev"


def _bank_paths(benchmark: str = DEFAULT_BENCHMARK) -> tuple[Path, Path]:
    base = _API_ROOT / "few_shot"
    return base / f"few_shot_{benchmark}.json", base / f"few_shot_{benchmark}.npz"


class FewShotExample(BaseModel):
    """Retrieved BIRD-train pair plus its cosine similarity to the user question."""

    db_id: str
    question: str
    gold_sql: str
    similarity: float


class _Embedder(Protocol):
    async def async_embed(self, text: str) -> list[float]: ...


class FewShotService:
    """Singleton-ish service: loads the bank once, retrieves on demand.

    Construction is cheap and side-effect-light; the actual disk reads happen
    in ``__init__`` once at app startup. Callers should reuse the same
    instance across requests (stashed on ``app.state`` and dependency-injected
    into routes).
    """

    def __init__(
        self,
        pairs_path: Path | None = None,
        emb_path: Path | None = None,
        benchmark: str = DEFAULT_BENCHMARK,
    ) -> None:
        if pairs_path is None or emb_path is None:
            pairs_path, emb_path = _bank_paths(benchmark)
        self._pairs: dict[str, list[dict]] = {}
        self._normed: dict[str, np.ndarray] = {}
        self._loaded = False

        if not pairs_path.exists() or not emb_path.exists():
            log.warning(
                "few_shot.bank_missing",
                pairs_path=str(pairs_path),
                emb_path=str(emb_path),
            )
            return

        try:
            self._pairs = json.loads(pairs_path.read_text())
            with np.load(emb_path) as npz:
                for key in npz.files:
                    if not key.startswith("emb__"):
                        continue
                    db_id = key[len("emb__") :]
                    mat = np.asarray(npz[key], dtype=np.float32)
                    if mat.ndim != 2 or mat.size == 0:
                        continue
                    # Bank is already L2-normalised at the stored dim; this
                    # is a defensive renorm so callers can ship arbitrary
                    # bank builds without surprises.
                    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10
                    self._normed[db_id] = (mat / norms).astype(np.float32)
            self._loaded = True
            total_pairs = sum(len(v) for v in self._pairs.values())
            log.info(
                "few_shot.bank_loaded",
                dbs=len(self._normed),
                pairs=total_pairs,
                emb_dim=next(iter(self._normed.values())).shape[1]
                if self._normed
                else 0,
            )
        except Exception as exc:  # noqa: BLE001 — never fail app startup
            log.warning(
                "few_shot.bank_load_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            self._pairs = {}
            self._normed = {}
            self._loaded = False

    @property
    def is_active(self) -> bool:
        """True if the bank loaded successfully and has at least one DB."""
        return self._loaded and bool(self._normed)

    @property
    def db_ids(self) -> list[str]:
        """List of db_ids the bank covers."""
        return sorted(self._normed.keys())

    async def retrieve(
        self, question: str, db_id: str, *, llm: "_Embedder | GeminiLLM"
    ) -> FewShotExample | None:
        """Return the most-similar BIRD-train QA pair for ``db_id`` (cosine top-1).

        Returns ``None`` when the bank has no rows for ``db_id``, the embedding
        call fails, or the bank itself is unavailable. Never raises.
        """
        if not self.is_active or db_id not in self._normed:
            return None
        if not question or not question.strip():
            return None

        try:
            raw = await llm.async_embed(question)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "few_shot.embed_failed",
                db_id=db_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None
        if not raw:
            return None

        # Slice + re-normalize so the live embedding matches the stored
        # truncated dim. ``gemini-embedding-001`` is Matryoshka, so the
        # leading prefix carries the same semantic information as the full
        # vector — this is the officially-supported MRL truncation pattern.
        q = np.asarray(raw[:EMBEDDING_DIM], dtype=np.float32)
        if q.size == 0:
            return None
        q = q / (np.linalg.norm(q) + 1e-10)

        mat = self._normed[db_id]
        # Defensive: only compare the prefix the bank actually stores.
        if mat.shape[1] != q.shape[0]:
            dim = min(mat.shape[1], q.shape[0])
            mat = mat[:, :dim]
            q = q[:dim]
            q = q / (np.linalg.norm(q) + 1e-10)

        scores = mat @ q
        best = int(np.argmax(scores))
        sim = float(scores[best])
        pair = self._pairs.get(db_id, [])[best] if best < len(self._pairs.get(db_id, [])) else None
        if pair is None:
            return None
        return FewShotExample(
            db_id=db_id,
            question=str(pair.get("question", "")),
            gold_sql=str(pair.get("gold_sql", "")),
            similarity=sim,
        )


# Module-level singleton. Initialised lazily on first ``get_few_shot_service``
# call so unit tests can set up their own instance via ``set_few_shot_service``
# before any request fires.
_SINGLETON: FewShotService | None = None


def get_few_shot_service() -> FewShotService:
    """Return the process-wide singleton, building it on first use.

    Loading the bank reads ~750 KB off disk and takes a few ms; doing it once
    per process (rather than per request) is the whole point. Tests can
    override the singleton via ``set_few_shot_service``.
    """
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = FewShotService()
    return _SINGLETON


def set_few_shot_service(svc: FewShotService | None) -> None:
    """Test hook — replace the module singleton (or clear it with ``None``)."""
    global _SINGLETON
    _SINGLETON = svc


async def prefetch_few_shot_example(
    svc: FewShotService,
    llm: "_Embedder | GeminiLLM",
    question: str,
    db_id: str,
) -> FewShotExample | None:
    """Best-effort retrieval helper meant for ``_preflight_concurrent``.

    Wraps ``svc.retrieve`` in a swallow-all guard so that a failing few-shot
    lookup can never break a chat turn. Returns ``None`` on any error.
    """
    try:
        return await svc.retrieve(question, db_id, llm=llm)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "few_shot.prefetch_failed",
            db_id=db_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


# asyncio re-export used by callers that want to fire-and-forget; keeps the
# import surface small.
__all__ = [
    "FewShotExample",
    "FewShotService",
    "get_few_shot_service",
    "set_few_shot_service",
    "prefetch_few_shot_example",
    "asyncio",
]
