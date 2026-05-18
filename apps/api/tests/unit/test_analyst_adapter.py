"""Unit tests for the analyst adapter.

Covers:
  - Chunk sequence order (Tier-3 pipeline transparency + synthetic tier-2 pair).
  - AnalystCollector can consume the stream and populate analyst_sql / analyst_rows.
  - Error path emits a vendored error chunk.
  - Adapter signature matches the vendored contract (kwargs the orchestrator passes
    are accepted and ignored).

The pipeline is mocked by monkey-patching ``default_pipeline`` to a stub that
emits a deterministic chunk sequence via the emitter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from insightxpert_api.agents import analyst as analyst_module
from insightxpert_api.sse.chunks import (
    ChunkType,
    ErrorPayload,
    LinkedSchemaFinalPayload,
    ProfileLoadedPayload,
    RowsReturnedPayload,
    SchemaLinkingStartedPayload,
    SQLExecutingPayload,
    SQLGeneratedPayload,
)
from insightxpert_api.vendored.agents_core.api.models import ChatChunk as VendoredChatChunk
from insightxpert_api.vendored.agents_core.common import AnalystCollector


@dataclass
class _FakeConfig:
    gemini_api_key: str = "fake"
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    max_refinement_iterations: int = 2
    sql_row_limit: int = 1000
    bundled_dbs_dir: str = "./Databases"
    storage_backend: str = "local"
    local_storage_root: str = "./var/storage"


class _FakeRag:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, bool]] = []

    def add_qa_pair(self, *, question: str, sql: str, sql_valid: bool = True) -> None:
        self.saved.append((question, sql, sql_valid))


class _StubPipeline:
    """A fake pipeline whose ``run_scalar`` emits a canned chunk sequence.

    Exercises every Tier-3 type the adapter is responsible for translating.
    """

    def __init__(self, sql: str = "SELECT 1 AS n", rows: list | None = None) -> None:
        self._sql = sql
        self._rows = rows if rows is not None else [[1]]

    async def run_scalar(self, ctx, _seed) -> None:
        em = ctx.emitter
        await em.emit(
            ChunkType.PROFILE_LOADED,
            ProfileLoadedPayload(db_id="toy", table_count=1, column_count=1, from_cache=True),
        )
        await em.emit(
            ChunkType.SCHEMA_LINKING_STARTED,
            SchemaLinkingStartedPayload(question="Q?", db_id="toy"),
        )
        await em.emit(
            ChunkType.LINKED_SCHEMA_FINAL,
            LinkedSchemaFinalPayload(
                schema_text="CREATE TABLE t(n INTEGER)",
                linked_tables=["t"],
                linked_columns=["t.n"],
                column_sources={"t.n": ["trial_sql"]},
            ),
        )
        await em.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=self._sql, iteration=0))
        await em.emit(ChunkType.SQL_EXECUTING, SQLExecutingPayload(sql=self._sql))
        await em.emit(
            ChunkType.ROWS_RETURNED,
            RowsReturnedPayload(
                columns=["n"], row_count=len(self._rows), rows=self._rows, execution_time_ms=1
            ),
        )
        ctx.state["rows"] = {"columns": ["n"], "rows": self._rows, "execution_time_ms": 1}
        ctx.state["answer"] = "one row."


@pytest.fixture
def _patch_pipeline(monkeypatch):
    """Replace default_pipeline with our stub so no LLM/DB is touched."""

    stub = _StubPipeline()

    def _fake_default_pipeline(_settings, _db_svc, _prof_svc, **_kwargs):
        return stub

    monkeypatch.setattr(analyst_module, "default_pipeline", _fake_default_pipeline)
    return stub


# Stub services — the adapter falls through to build its own via build_store
# when these aren't passed; we side-step that entire path by passing sentinels.
_FAKE_DB_SVC = object()
_FAKE_PROF_SVC = object()


@pytest.mark.asyncio
async def test_analyst_emits_expected_chunk_sequence(_patch_pipeline, tmp_path):
    config = _FakeConfig(local_storage_root=str(tmp_path))
    rag = _FakeRag()

    chunks: list[VendoredChatChunk] = []
    async for chunk in analyst_module.analyst_loop(
        question="How many rows?",
        llm=None,
        db=None,
        rag=rag,
        config=config,
        conversation_id="c1",
        history=[],
        db_id="toy",
        session_id="s1",
        db_svc=_FAKE_DB_SVC,
        prof_svc=_FAKE_PROF_SVC,
        # Extra kwargs the real orchestrator passes — must be swallowed.
        ddl_override=None,
        documentation_override=None,
        stats_context=None,
        stats_groups=[],
        clarification_enabled=False,
        rag_retrieval=True,
        allowed_tables=None,
        dataset_id=None,
        org_id=None,
        column_count=None,
    ):
        chunks.append(chunk)

    types = [c.type for c in chunks]

    # Tier-3 transparency in order.
    assert types.index("profile_loaded") < types.index("schema_linking_started")
    assert types.index("schema_linking_started") < types.index("linked_schema_final")
    assert types.index("linked_schema_final") < types.index("sql_generated")
    assert types.index("sql_generated") < types.index("sql_executing")
    assert types.index("sql_executing") < types.index("rows_returned")
    assert types.index("rows_returned") < types.index("answer_generated")

    # Synthetic tier-2 pre-pair must still be present, bracketed BEFORE the
    # SQL exec — AnalystCollector.sql still relies on the flat-shape ``sql``
    # chunk, and the orchestrator log still consumes ``tool_call``. The
    # POST-execution ``tool_result`` was removed on 2026-05-01: the canonical
    # rows_returned chunk is now the sole result-of-execution emission, and
    # AnalystCollector reads rows from it directly.
    assert "sql" in types
    assert "tool_call" in types
    assert types.index("sql") < types.index("sql_executing")
    assert types.index("tool_call") < types.index("sql_executing")
    assert "tool_result" not in types, (
        "synthetic tool_result should no longer be emitted after rows_returned"
    )

    # Answer chunk (flat vendored shape) is last-ish and carries content.
    answer_chunks = [c for c in chunks if c.type == "answer"]
    assert len(answer_chunks) == 1
    assert answer_chunks[0].content == "one row."


@pytest.mark.asyncio
async def test_analyst_stream_is_analyst_collector_compatible(_patch_pipeline, tmp_path):
    """The critical orchestrator-compat check: AnalystCollector must see sql/rows/answer."""
    config = _FakeConfig(local_storage_root=str(tmp_path))
    collector = AnalystCollector()

    async for chunk in analyst_module.analyst_loop(
        question="How many rows?",
        llm=None,
        db=None,
        rag=None,
        config=config,
        conversation_id="c1",
        db_id="toy",
        session_id="s1",
        db_svc=_FAKE_DB_SVC,
        prof_svc=_FAKE_PROF_SVC,
    ):
        collector.process_chunk(chunk)

    assert collector.sql == "SELECT 1 AS n"
    assert collector.rows == [{"n": 1}]
    assert collector.answer == "one row."
    assert collector.had_error is False


@pytest.mark.asyncio
async def test_analyst_rag_autosave_fires(_patch_pipeline, tmp_path):
    config = _FakeConfig(local_storage_root=str(tmp_path))
    rag = _FakeRag()

    async for _ in analyst_module.analyst_loop(
        question="Q",
        llm=None,
        db=None,
        rag=rag,
        config=config,
        conversation_id="c1",
        db_id="toy",
        session_id="s1",
        db_svc=_FAKE_DB_SVC,
        prof_svc=_FAKE_PROF_SVC,
    ):
        pass

    assert rag.saved == [("Q", "SELECT 1 AS n", True)]


@pytest.mark.asyncio
async def test_analyst_missing_db_id_emits_error(tmp_path):
    """Without db_id, the adapter must fail fast with an error chunk — no pipeline run."""
    config = _FakeConfig(local_storage_root=str(tmp_path))

    chunks: list[VendoredChatChunk] = []
    async for chunk in analyst_module.analyst_loop(
        question="Q", llm=None, db=None, rag=None, config=config, conversation_id="c1",
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].type == "error"
    assert chunks[0].data == {"code": "analyst_missing_db_id"}


@pytest.mark.asyncio
async def test_analyst_error_in_pipeline_propagates(monkeypatch, tmp_path):
    """If the pipeline raises, the adapter surfaces an error chunk and keeps the collector error flag hot."""
    class _BoomPipeline:
        async def run_scalar(self, _ctx, _seed):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        analyst_module, "default_pipeline", lambda *a, **k: _BoomPipeline()
    )

    config = _FakeConfig(local_storage_root=str(tmp_path))
    collector = AnalystCollector()

    async for chunk in analyst_module.analyst_loop(
        question="Q", llm=None, db=None, rag=None, config=config,
        conversation_id="c1", db_id="toy", session_id="s1",
        db_svc=_FAKE_DB_SVC, prof_svc=_FAKE_PROF_SVC,
    ):
        collector.process_chunk(chunk)

    assert collector.had_error is True


class _RefinerRecoveryPipeline:
    """Simulates executor error followed by successful refiner recovery.

    Chunk sequence mirrors what happens in production when the first executed
    SQL fails and ``sql_refiner`` successfully produces a new SQL that returns
    rows: ``SQL_GENERATED`` (iter 0) -> ``SQL_EXECUTING`` -> ``ERROR`` ->
    ``SQL_GENERATED`` (iter 1) -> ``SQL_EXECUTING`` -> ``ROWS_RETURNED``.
    """

    async def run_scalar(self, ctx, _seed) -> None:
        em = ctx.emitter
        bad_sql = "SELECT * FROM nonexistent"
        good_sql = "SELECT n FROM t"
        good_rows = [[42]]
        await em.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=bad_sql, iteration=0))
        await em.emit(ChunkType.SQL_EXECUTING, SQLExecutingPayload(sql=bad_sql))
        await em.emit(
            ChunkType.ERROR,
            ErrorPayload(code="sql_execution_failed", detail="no such table: nonexistent"),
        )
        # Refiner recovers.
        await em.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=good_sql, iteration=1))
        await em.emit(ChunkType.SQL_EXECUTING, SQLExecutingPayload(sql=good_sql))
        await em.emit(
            ChunkType.ROWS_RETURNED,
            RowsReturnedPayload(
                columns=["n"], row_count=1, rows=good_rows, execution_time_ms=2
            ),
        )
        ctx.state["rows"] = {"columns": ["n"], "rows": good_rows, "execution_time_ms": 2}
        ctx.state["answer"] = "refined ok."


@pytest.mark.asyncio
async def test_analyst_recovers_from_executor_error_via_refiner(monkeypatch, tmp_path):
    """Regression: a transient executor error followed by a refiner success must
    NOT leave had_error=True, must emit answer_generated, and must populate the
    tool_result with the refined rows. This gates orchestrator Phase-2 enrichment.
    """
    monkeypatch.setattr(
        analyst_module, "default_pipeline", lambda *a, **k: _RefinerRecoveryPipeline()
    )
    config = _FakeConfig(local_storage_root=str(tmp_path))
    collector = AnalystCollector()

    chunks: list[VendoredChatChunk] = []
    async for chunk in analyst_module.analyst_loop(
        question="Q", llm=None, db=None, rag=None, config=config,
        conversation_id="c1", db_id="toy", session_id="s1",
        db_svc=_FAKE_DB_SVC, prof_svc=_FAKE_PROF_SVC,
    ):
        chunks.append(chunk)
        collector.process_chunk(chunk)

    types = [c.type for c in chunks]
    # Phase-2 gate: answer_generated AND answer must both be emitted despite
    # the intermediate error.
    assert "answer_generated" in types, f"missing answer_generated; got {types}"
    assert "answer" in types, f"missing answer; got {types}"

    # The refined rows must reach the collector via rows_returned (the
    # synthetic tool_result post-emission was removed on 2026-05-01).
    rows_returned = [c for c in chunks if c.type == "rows_returned"]
    assert len(rows_returned) == 1
    assert rows_returned[0].data["rows"] == [[42]]
    assert rows_returned[0].data["columns"] == ["n"]

    # AnalystCollector state must reflect recovery.
    assert collector.had_error is False
    assert collector.sql == "SELECT n FROM t"
    assert collector.rows == [{"n": 42}]
    assert collector.answer == "refined ok."


@pytest.mark.asyncio
async def test_rows_returned_is_canonical_result_chunk(_patch_pipeline, tmp_path):
    """rows_returned carries the canonical result payload; no duplicate tool_result."""
    config = _FakeConfig(local_storage_root=str(tmp_path))

    chunks: list[VendoredChatChunk] = []
    async for chunk in analyst_module.analyst_loop(
        question="Q", llm=None, db=None, rag=None, config=config,
        conversation_id="c1", db_id="toy", session_id="s1",
        db_svc=_FAKE_DB_SVC, prof_svc=_FAKE_PROF_SVC,
    ):
        chunks.append(chunk)

    rows_returned = [c for c in chunks if c.type == "rows_returned"]
    assert len(rows_returned) == 1
    data = rows_returned[0].data
    assert data is not None
    assert data["columns"] == ["n"]
    assert data["rows"] == [[1]]
    assert data["row_count"] == 1
    # Bug fix 2026-05-01: no synthetic Tier-2 tool_result after rows_returned.
    assert all(c.type != "tool_result" for c in chunks)


def test_analyst_collector_captures_rows_from_rows_returned():
    """AnalystCollector reads rows from the Tier-3 rows_returned chunk directly,
    converting positional rows + columns into the dict shape downstream
    consumers expect (mirrors the legacy tool_result branch's output).
    """
    collector = AnalystCollector()
    chunk = VendoredChatChunk(
        type="rows_returned",
        data={
            "columns": ["a", "b"],
            "rows": [[1, 2], [3, 4]],
            "row_count": 2,
            "execution_time_ms": 5,
        },
        conversation_id="c1",
        timestamp=0.0,
    )

    collector.process_chunk(chunk)

    assert collector.rows == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
