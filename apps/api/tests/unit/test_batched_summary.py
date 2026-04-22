"""Unit tests for BatchedSummaryGenerator.

LLM is always mocked — these tests must never hit a live API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from insightxpert_api.profiling.batched_summary import BatchedSummaryGenerator
from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnStats,
    DatabaseProfile,
    TableProfile,
)
from insightxpert_api.vendored.pipeline_core.models.schema import (
    ColumnSchema,
    DatabaseSchema,
    TableSchema,
)


@dataclass
class _FakeResp:
    content: str


def _make_profile(n_cols: int) -> tuple[DatabaseProfile, DatabaseSchema]:
    cols = [
        ColumnProfile(
            name=f"col_{i}",
            type="TEXT",
            stats=ColumnStats(count=10, null_count=0, distinct_count=5),
        )
        for i in range(n_cols)
    ]
    profile = DatabaseProfile(
        db_id="unit",
        tables=[TableProfile(name="t", row_count=10, columns=cols)],
    )
    schema_cols = [ColumnSchema(name=c.name, type="TEXT") for c in cols]
    schema = DatabaseSchema(
        db_id="unit",
        tables=[TableSchema(name="t", columns=schema_cols)],
    )
    return profile, schema


def _full_response(col_names: list[str]) -> str:
    return json.dumps(
        {
            name: {
                "short_summary": f"short for {name}",
                "long_summary": f"long for {name}",
            }
            for name in col_names
        }
    )


async def test_batched_summary_45_cols_fires_3_batch_calls():
    """45 columns ÷ batch_size 20 → 3 LLM calls (20, 20, 5)."""
    profile, schema = _make_profile(45)

    llm = AsyncMock()

    async def _answer(prompt: str) -> str:
        # Reply with a well-formed object covering every column named in the prompt.
        names: list[str] = []
        for line in prompt.splitlines():
            if "column_name:" in line:
                names.append(line.split("column_name:", 1)[1].strip())
        return _full_response(names)

    llm.async_generate = AsyncMock(side_effect=_answer)

    gen = BatchedSummaryGenerator(llm, batch_size=20)
    result = await gen.async_generate(schema, profile)

    assert llm.async_generate.await_count == 3
    populated = [c for t in result.tables for c in t.columns if c.short_summary]
    assert len(populated) == 45


async def test_batched_summary_partial_response_falls_back(capsys):
    """A batch of 20 that returns only 18 entries → 2 single-col fallbacks.

    Also asserts the ``profiling.batch_response_partial`` structlog event is emitted.
    """
    profile, schema = _make_profile(20)

    async def _answer(prompt: str) -> str:
        # Batch prompts have multiple "column_name:" lines; single-col fallbacks
        # use the compact "column: <name>" shape.
        names: list[str] = [
            line.split("column_name:", 1)[1].strip()
            for line in prompt.splitlines()
            if "column_name:" in line
        ]
        if names:
            # Simulate a partial batch response — drop the last 2.
            return _full_response(names[:-2])
        # Single-col fallback: a one-key JSON object is enough.
        return json.dumps(
            {"short_summary": "single-short", "long_summary": "single-long"}
        )

    llm = AsyncMock()
    llm.async_generate = AsyncMock(side_effect=_answer)

    gen = BatchedSummaryGenerator(llm, batch_size=20)
    result = await gen.async_generate(schema, profile)

    # One batch call + two single-column fallbacks = 3 total
    assert llm.async_generate.await_count == 3

    # All 20 columns ended up populated (18 from batch, 2 from fallback)
    populated = [c for t in result.tables for c in t.columns if c.short_summary]
    assert len(populated) == 20

    # batch_response_partial was emitted. Captured via stdout — structlog's
    # PrintLoggerFactory writes structured events there, and re-configuring
    # it here is unreliable because loggers cache on first use across tests.
    captured = capsys.readouterr().out
    assert "profiling.batch_response_partial" in captured


async def test_batched_summary_empty_profile_is_noop():
    profile, schema = _make_profile(0)
    llm = AsyncMock()
    llm.async_generate = AsyncMock(return_value="{}")

    result = await BatchedSummaryGenerator(llm, batch_size=20).async_generate(
        schema, profile
    )
    assert llm.async_generate.await_count == 0
    assert result is profile


async def test_batched_summary_rejects_bad_batch_size():
    with pytest.raises(ValueError):
        BatchedSummaryGenerator(AsyncMock(), batch_size=0)
