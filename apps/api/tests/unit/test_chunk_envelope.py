"""Unified envelope: type + data + conversation_id + timestamp, Tier-4 types exist."""

from __future__ import annotations

from insightxpert_api.sse.chunks import (
    AgentTracePayload,
    AnswerGeneratedPayload,
    ChatChunk,
    ChunkType,
    EnrichmentTracePayload,
    InsightPayload,
    OrchestratorPlanPayload,
    RowsReturnedPayload,
    SqlGeneratedPayload,
    StatsContextPayload,
)


def test_envelope_shape_is_strict():
    chunk = ChatChunk(
        type=ChunkType.sql_generated,
        data=SqlGeneratedPayload(sql="select 1", iteration=0),
    )
    d = chunk.model_dump()
    assert set(d) == {"type", "data", "conversation_id", "timestamp"}


def test_tier4_types_exist():
    # Attribute access verifies the enum members are defined
    assert ChunkType.stats_context.value == "stats_context"
    assert ChunkType.orchestrator_plan.value == "orchestrator_plan"
    assert ChunkType.agent_trace.value == "agent_trace"
    assert ChunkType.enrichment_trace.value == "enrichment_trace"
    assert ChunkType.insight.value == "insight"
    assert ChunkType.clarification.value == "clarification"


def test_tier4_payload_models_exist_and_validate():
    StatsContextPayload(content="p95=120ms", groups=["latency"])
    OrchestratorPlanPayload(reasoning="plan", tasks=[])
    AgentTracePayload(
        task_id="t1",
        agent="analyst",
        category="analytics",
        task="count rows",
        success=True,
        duration_ms=42,
    )
    EnrichmentTracePayload(
        source_index=0,
        category="drilldown",
        question="why?",
        rationale="because",
        success=True,
        duration_ms=10,
    )
    InsightPayload(content="hello", agent="analyst")


def test_rows_returned_payload_required_fields():
    p = RowsReturnedPayload(columns=["a"], rows=[[1]], row_count=1, execution_time_ms=5)
    assert p.row_count == 1


def test_answer_generated_reads_from_data_text():
    chunk = ChatChunk(
        type=ChunkType.answer_generated,
        data=AnswerGeneratedPayload(text="hello"),
    )
    assert chunk.data.text == "hello"


def test_lowercase_and_upper_enum_members_are_same_value():
    assert ChunkType.sql_generated.value == ChunkType.SQL_GENERATED.value == "sql_generated"
