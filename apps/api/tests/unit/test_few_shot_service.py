"""Unit tests for ``services.few_shot_service`` and the SQL-gen prompt wiring.

These tests pin three things:
  1. ``FewShotService.retrieve`` returns the highest-cosine pair for the
     queried db_id when called with a tiny in-memory bank — no reliance on
     the live committed bank or live Gemini.
  2. A missing/empty bank yields ``is_active=False`` and ``retrieve``
     short-circuits to ``None`` without raising.
  3. ``SqlGeneratorStage`` renders the prompt with the few-shot example's
     ``Question:`` / ``SQL:`` lines when ``ctx.state["few_shot_example"]``
     is set, and skips the block entirely when it isn't.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from insightxpert_api.pipeline.generator_stage import SqlGeneratorStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.services.few_shot_service import (
    EMBEDDING_DIM,
    FewShotExample,
    FewShotService,
)


# ---------------------------------------------------------------------------
# Bank fixtures
# ---------------------------------------------------------------------------


def _build_bank(tmp_path: Path) -> tuple[Path, Path]:
    """Write a tiny 3-pair / 2-DB bank to ``tmp_path/few_shot/`` and return paths."""
    base = tmp_path / "few_shot"
    base.mkdir(parents=True, exist_ok=True)
    pairs_path = base / "few_shot_test.json"
    emb_path = base / "few_shot_test.npz"

    pairs = {
        "db_a": [
            {"question": "How many cats are there?", "gold_sql": "SELECT COUNT(*) FROM cats"},
            {"question": "Which dogs bark loudest?", "gold_sql": "SELECT name FROM dogs ORDER BY bark DESC"},
        ],
        "db_b": [
            {"question": "Average GDP by country?", "gold_sql": "SELECT country, AVG(gdp) FROM econ GROUP BY country"},
        ],
    }
    pairs_path.write_text(json.dumps(pairs))

    # Three orthogonal 1536-d unit vectors, one per pair.
    def _onehot(idx: int) -> np.ndarray:
        v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        v[idx] = 1.0
        return v

    emb = {
        "emb__db_a": np.stack([_onehot(0), _onehot(1)]).astype(np.float32),
        "emb__db_b": np.stack([_onehot(2)]).astype(np.float32),
    }
    np.savez(emb_path, **emb)
    return pairs_path, emb_path


class _FakeEmbedder:
    """Returns a 1-hot vector at ``hot_index`` so the cosine match is deterministic."""

    def __init__(self, hot_index: int) -> None:
        self._hot = hot_index

    async def async_embed(self, text: str) -> list[float]:  # noqa: ARG002
        v = [0.0] * EMBEDDING_DIM
        v[self._hot] = 1.0
        return v


# ---------------------------------------------------------------------------
# FewShotService tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_returns_top_match(tmp_path: Path) -> None:
    pairs_path, emb_path = _build_bank(tmp_path)
    svc = FewShotService(pairs_path=pairs_path, emb_path=emb_path)
    assert svc.is_active
    assert set(svc.db_ids) == {"db_a", "db_b"}

    # The 0-th stored embedding for db_a is "How many cats are there?".
    ex = await svc.retrieve("doesn't matter", "db_a", llm=_FakeEmbedder(hot_index=0))
    assert ex is not None
    assert isinstance(ex, FewShotExample)
    assert ex.question == "How many cats are there?"
    assert ex.gold_sql == "SELECT COUNT(*) FROM cats"
    assert ex.similarity == pytest.approx(1.0)
    assert ex.db_id == "db_a"

    # 1-hot at index 1 should pick the dogs pair.
    ex2 = await svc.retrieve("anything", "db_a", llm=_FakeEmbedder(hot_index=1))
    assert ex2 is not None
    assert ex2.question.startswith("Which dogs bark")


@pytest.mark.asyncio
async def test_retrieve_unknown_db_id(tmp_path: Path) -> None:
    pairs_path, emb_path = _build_bank(tmp_path)
    svc = FewShotService(pairs_path=pairs_path, emb_path=emb_path)
    ex = await svc.retrieve("q", "no_such_db", llm=_FakeEmbedder(hot_index=0))
    assert ex is None


@pytest.mark.asyncio
async def test_missing_bank_is_noop(tmp_path: Path) -> None:
    """Bank files that don't exist → service is inert; retrieve returns None."""
    svc = FewShotService(
        pairs_path=tmp_path / "does_not_exist.json",
        emb_path=tmp_path / "does_not_exist.npz",
    )
    assert not svc.is_active
    assert svc.db_ids == []
    ex = await svc.retrieve("q", "db_a", llm=_FakeEmbedder(hot_index=0))
    assert ex is None


@pytest.mark.asyncio
async def test_embed_failure_returns_none(tmp_path: Path) -> None:
    """A raising embedder must be swallowed — chat turn never breaks."""
    pairs_path, emb_path = _build_bank(tmp_path)
    svc = FewShotService(pairs_path=pairs_path, emb_path=emb_path)

    class _Boom:
        async def async_embed(self, text: str) -> list[float]:  # noqa: ARG002
            raise RuntimeError("rate limit")

    ex = await svc.retrieve("q", "db_a", llm=_Boom())
    assert ex is None


# ---------------------------------------------------------------------------
# SQL-gen prompt wiring tests
# ---------------------------------------------------------------------------


def _write_minimal_prompt(tmp_path: Path) -> Path:
    """Drop a stub prompt template that mirrors the production few-shot block."""
    p = tmp_path / "stub_sql_gen.j2"
    p.write_text(
        "Q: {{ question }}\n"
        "S: {{ schema_text }}\n"
        "{% if few_shot_example %}"
        "EX_QUESTION: {{ few_shot_example.question }}\n"
        "EX_SQL: {{ few_shot_example.gold_sql }}\n"
        "{% endif %}"
    )
    return p


class _StubLLM:
    """Captures the rendered prompt and returns a fenced SQL block."""

    def __init__(self) -> None:
        self.last_prompt: str = ""

    async def async_generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return "```sql\nSELECT 1\n```"


@pytest.mark.asyncio
async def test_generator_stage_threads_few_shot_into_prompt(tmp_path: Path) -> None:
    prompt_path = _write_minimal_prompt(tmp_path)
    llm = _StubLLM()
    stage = SqlGeneratorStage(llm=llm, prompt_path=str(prompt_path))

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["question"] = "How many cats?"
    ctx.state["schema_text"] = "Table cats(name TEXT)"
    ctx.state["few_shot_example"] = FewShotExample(
        db_id="db_a",
        question="Total dogs?",
        gold_sql="SELECT COUNT(*) FROM dogs",
        similarity=0.92,
    )

    sql = await stage.run(ctx, None)
    assert sql == "SELECT 1"
    assert "EX_QUESTION: Total dogs?" in llm.last_prompt
    assert "EX_SQL: SELECT COUNT(*) FROM dogs" in llm.last_prompt


@pytest.mark.asyncio
async def test_generator_stage_skips_block_when_no_few_shot(tmp_path: Path) -> None:
    prompt_path = _write_minimal_prompt(tmp_path)
    llm = _StubLLM()
    stage = SqlGeneratorStage(llm=llm, prompt_path=str(prompt_path))

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["question"] = "How many cats?"
    ctx.state["schema_text"] = "Table cats(name TEXT)"

    await stage.run(ctx, None)
    assert "EX_QUESTION" not in llm.last_prompt
    assert "EX_SQL" not in llm.last_prompt


# ---------------------------------------------------------------------------
# Concurrency check: prefetch_few_shot races alongside another await
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prefetch_runs_concurrently_with_other_awaits(tmp_path: Path) -> None:
    """If the embed call sleeps 100ms and another coroutine sleeps 100ms in parallel,
    total wall time should be ~100ms — proving the few-shot prefetch doesn't
    serialise behind whatever else preflight is doing."""
    import time

    from insightxpert_api.services.few_shot_service import prefetch_few_shot_example

    pairs_path, emb_path = _build_bank(tmp_path)
    svc = FewShotService(pairs_path=pairs_path, emb_path=emb_path)

    class _SlowEmbedder:
        async def async_embed(self, text: str) -> list[float]:  # noqa: ARG002
            await asyncio.sleep(0.1)
            v = [0.0] * EMBEDDING_DIM
            v[0] = 1.0
            return v

    async def _other_work() -> str:
        await asyncio.sleep(0.1)
        return "done"

    start = time.perf_counter()
    ex, other = await asyncio.gather(
        prefetch_few_shot_example(svc, _SlowEmbedder(), "q", "db_a"),
        _other_work(),
    )
    elapsed = time.perf_counter() - start

    assert other == "done"
    assert ex is not None
    assert ex.question.startswith("How many cats")
    assert elapsed < 0.18, f"few-shot ran sequentially with the other work: {elapsed:.3f}s"
