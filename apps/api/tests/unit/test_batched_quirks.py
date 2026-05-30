"""Unit tests for BatchedQuirkDetector. LLM mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from insightxpert_api.profiling.batched_quirks import BatchedQuirkDetector
from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnQuirks,
    ColumnStats,
    DatabaseProfile,
    TableProfile,
)
from insightxpert_api.vendored.pipeline_core.models.schema import (
    ColumnSchema,
    DatabaseSchema,
    TableSchema,
)


def _cryptic_col(name: str) -> ColumnProfile:
    # "looks_cryptic" returns True for <=4 char non-common-word names.
    return ColumnProfile(
        name=name,
        type="TEXT",
        stats=ColumnStats(
            count=10, null_count=0, distinct_count=5,
            sample_values=["abc", "def"],
        ),
        quirks=ColumnQuirks(),
    )


def _make_profile(n: int) -> tuple[DatabaseProfile, DatabaseSchema]:
    # All names are 3-char cryptic codes → every col is LLM-worthy.
    cols = [_cryptic_col(f"c{i:02d}") for i in range(n)]
    profile = DatabaseProfile(
        db_id="unit",
        tables=[TableProfile(name="t", row_count=10, columns=cols)],
    )
    schema = DatabaseSchema(
        db_id="unit",
        tables=[
            TableSchema(
                name="t",
                columns=[ColumnSchema(name=c.name, type="TEXT") for c in cols],
            )
        ],
    )
    return profile, schema


def _full_response(names: list[str]) -> str:
    return json.dumps(
        {n: {"quirks": [f"phrase for {n}", "alt"]} for n in names}
    )


async def test_batched_quirks_45_cols_fires_3_batch_calls():
    profile, schema = _make_profile(45)

    async def _answer(prompt: str) -> str:
        names = [
            line.split("column_name:", 1)[1].strip()
            for line in prompt.splitlines()
            if "column_name:" in line
        ]
        return _full_response(names)

    llm = AsyncMock()
    llm.async_generate = AsyncMock(side_effect=_answer)

    result = await BatchedQuirkDetector(llm, batch_size=20).async_enrich(
        profile, schema
    )
    assert llm.async_generate.await_count == 3
    # Every column should have aliases populated
    aliased = [
        c for t in result.tables for c in t.columns if c.quirks and c.quirks.aliases
    ]
    assert len(aliased) == 45


async def test_batched_quirks_partial_response_triggers_fallback(monkeypatch):
    import insightxpert_api.profiling.batched_quirks as bq
    from unittest.mock import MagicMock
    mock_log = MagicMock()
    monkeypatch.setattr(bq, "log", mock_log)

    profile, schema = _make_profile(20)

    async def _answer(prompt: str) -> str:
        names = [
            line.split("column_name:", 1)[1].strip()
            for line in prompt.splitlines()
            if "column_name:" in line
        ]
        if names:
            # Return only 18 entries for the single batch → 2 missing
            return _full_response(names[:-2])
        # Single-col fallback — compact JSON with "quirks"
        return json.dumps({"quirks": ["fallback phrase"]})

    llm = AsyncMock()
    llm.async_generate = AsyncMock(side_effect=_answer)

    result = await BatchedQuirkDetector(llm, batch_size=20).async_enrich(
        profile, schema
    )

    # 1 batch + 2 fallbacks = 3 calls
    assert llm.async_generate.await_count == 3
    aliased = [
        c for t in result.tables for c in t.columns if c.quirks and c.quirks.aliases
    ]
    assert len(aliased) == 20

    # Partial-response event was logged (captured via mock)
    assert any(
        call.args[0] == "profiling.batch_response_partial"
        for call in mock_log.warning.call_args_list
    )


async def test_batched_quirks_no_candidates_is_noop():
    """Columns that don't meet the vendored filters → 0 LLM calls."""
    # Use "name" — a _COMMON_SHORT_NAMES entry, so looks_cryptic returns False.
    col = ColumnProfile(
        name="name",
        type="TEXT",
        stats=ColumnStats(count=10, null_count=0, distinct_count=10,
                          sample_values=["alice", "bob"]),
        quirks=ColumnQuirks(),
    )
    profile = DatabaseProfile(
        db_id="unit",
        tables=[TableProfile(name="t", row_count=10, columns=[col])],
    )
    schema = DatabaseSchema(
        db_id="unit",
        tables=[TableSchema(name="t", columns=[ColumnSchema(name="name", type="TEXT")])],
    )

    llm = AsyncMock()
    llm.async_generate = AsyncMock(return_value="{}")
    await BatchedQuirkDetector(llm, batch_size=20).async_enrich(profile, schema)
    assert llm.async_generate.await_count == 0
