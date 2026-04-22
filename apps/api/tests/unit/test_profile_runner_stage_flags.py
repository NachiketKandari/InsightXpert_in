"""Unit tests for profiler stage flags + auto-disable guard. LLM mocked."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from insightxpert_api.pipeline.profiler_stage import build_profile


def _tiny_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, abc TEXT);
        INSERT INTO users(id, name, abc) VALUES (1, 'alice', 'x'), (2, 'bob', 'y');
        """
    )
    con.commit()
    con.close()


@pytest.fixture
def tiny_db(tmp_path):
    p = tmp_path / "tiny.sqlite"
    _tiny_db(p)
    return p


async def test_all_flags_off_skips_llm_stages(tiny_db):
    """Baseline: default build_profile fires no LLM work, no batched classes."""
    with patch(
        "insightxpert_api.profiling.batched_summary.BatchedSummaryGenerator.async_generate",
        new=AsyncMock(),
    ) as s, patch(
        "insightxpert_api.profiling.batched_quirks.BatchedQuirkDetector.async_enrich",
        new=AsyncMock(),
    ) as q:
        profile = await build_profile(
            db_id="tiny", db_path=str(tiny_db), llm=AsyncMock()
        )
    assert profile.db_id == "tiny"
    assert len(profile.tables) == 1
    assert s.await_count == 0
    assert q.await_count == 0


async def test_with_summaries_invokes_batched_summary(tiny_db):
    llm = AsyncMock()
    llm.async_generate = AsyncMock(return_value="{}")

    with patch(
        "insightxpert_api.profiling.batched_summary.BatchedSummaryGenerator.async_generate",
        new=AsyncMock(side_effect=lambda schema, profile, unified_evidence="": profile),
    ) as s, patch(
        "insightxpert_api.profiling.batched_quirks.BatchedQuirkDetector.async_enrich",
        new=AsyncMock(),
    ) as q:
        await build_profile(
            db_id="tiny", db_path=str(tiny_db), llm=llm,
            with_summaries=True,
        )
    assert s.await_count == 1
    assert q.await_count == 0


async def test_with_quirks_invokes_batched_quirks(tiny_db):
    llm = AsyncMock()
    with patch(
        "insightxpert_api.profiling.batched_summary.BatchedSummaryGenerator.async_generate",
        new=AsyncMock(),
    ) as s, patch(
        "insightxpert_api.profiling.batched_quirks.BatchedQuirkDetector.async_enrich",
        new=AsyncMock(side_effect=lambda profile, schema: profile),
    ) as q:
        await build_profile(
            db_id="tiny", db_path=str(tiny_db), llm=llm, with_quirks=True,
        )
    assert s.await_count == 0
    assert q.await_count == 1


async def test_batch_disabled_uses_vendored_summary(tiny_db):
    """batch_disabled=True should route through the vendored SummaryGenerator,
    not the batched one."""
    llm = AsyncMock()

    # Replace the entire vendored SummaryGenerator class with a stand-in — its
    # __init__ eagerly loads Jinja templates that aren't available from the
    # test CWD, so we can't patch only .async_generate.
    class _FakeVendored:
        instances: list["_FakeVendored"] = []

        def __init__(self, llm):
            _FakeVendored.instances.append(self)
            self.called = 0

        async def async_generate(self, schema, profile, unified_evidence=""):
            self.called += 1
            return profile

    with patch(
        "insightxpert_api.vendored.pipeline_core.profiler.summary_generator.SummaryGenerator",
        _FakeVendored,
    ), patch(
        "insightxpert_api.profiling.batched_summary.BatchedSummaryGenerator.async_generate",
        new=AsyncMock(),
    ) as batched_s:
        await build_profile(
            db_id="tiny", db_path=str(tiny_db), llm=llm,
            with_summaries=True, batch_disabled=True,
        )
    assert len(_FakeVendored.instances) == 1
    assert _FakeVendored.instances[0].called == 1
    assert batched_s.await_count == 0


async def test_auto_disable_over_column_threshold(tiny_db):
    """If columns > threshold, ALL 4 flags auto-disable."""
    llm = AsyncMock()
    # tiny DB has 3 columns; set threshold to 2 so guard fires.
    with patch(
        "insightxpert_api.profiling.batched_summary.BatchedSummaryGenerator.async_generate",
        new=AsyncMock(),
    ) as s, patch(
        "insightxpert_api.profiling.batched_quirks.BatchedQuirkDetector.async_enrich",
        new=AsyncMock(),
    ) as q:
        await build_profile(
            db_id="tiny", db_path=str(tiny_db), llm=llm,
            with_summaries=True, with_quirks=True, with_lsh=True, with_vectors=True,
            max_columns_for_llm=2,
        )
    assert s.await_count == 0
    assert q.await_count == 0


async def test_under_threshold_runs_flags(tiny_db):
    llm = AsyncMock()
    with patch(
        "insightxpert_api.profiling.batched_summary.BatchedSummaryGenerator.async_generate",
        new=AsyncMock(side_effect=lambda schema, profile, unified_evidence="": profile),
    ) as s:
        await build_profile(
            db_id="tiny", db_path=str(tiny_db), llm=llm,
            with_summaries=True, max_columns_for_llm=500,
        )
    assert s.await_count == 1
