"""SSE chunk taxonomy — the wire contract between pipeline/agents and UI.

Unified four-tier envelope (spec §8):
  - Tier-1: lifecycle (status, error, metrics)
  - Tier-2: generic tool call/result (tool_call, tool_result)
  - Tier-3: pipeline transparency (profile_loaded, schema_linking_started,
    candidate_sqls_generated, literals_extracted, semantic_matches,
    join_paths_added, linked_schema_final, sql_generated, sql_executing,
    rows_returned, answer_generated)
  - Tier-4: orchestration transparency (stats_context, orchestrator_plan,
    agent_trace, enrichment_trace, insight, clarification)

Every chunk is strictly ``{type, data, conversation_id, timestamp}`` on the
wire. Legacy flat shapes (top-level ``sql`` / ``answer`` / ``tool_name``) are
gone; everything lives inside ``data``.

Payload shapes here are the SOURCE OF TRUTH for the generated TypeScript types
in ``packages/types``. Keep fields precise; avoid ``dict[str, Any]`` unless the
shape is genuinely open-ended.

The ``ChunkType`` enum exposes lowercase member names (``ChunkType.sql_generated``)
that match the wire value, plus UPPER_CASE aliases (``ChunkType.SQL_GENERATED``)
retained for Phase A emitter/test call-sites.
"""

from __future__ import annotations

import json
from enum import Enum
from time import time
from typing import Union

from pydantic import BaseModel, Field


class ChunkType(str, Enum):
    """Closed set of SSE chunk types. FE chunk renderers dispatch on this value."""

    # --- Tier-1: lifecycle -----------------------------------------------
    status = "status"
    error = "error"
    metrics = "metrics"

    # --- Tier-2: generic tool protocol -----------------------------------
    tool_call = "tool_call"
    tool_result = "tool_result"

    # --- Tier-3: pipeline transparency -----------------------------------
    profile_loaded = "profile_loaded"
    schema_linking_started = "schema_linking_started"
    candidate_sqls_generated = "candidate_sqls_generated"
    literals_extracted = "literals_extracted"
    semantic_matches = "semantic_matches"
    join_paths_added = "join_paths_added"
    linked_schema_final = "linked_schema_final"
    sql_generated = "sql_generated"
    sql_executing = "sql_executing"
    rows_returned = "rows_returned"
    answer_generated = "answer_generated"

    # --- Profiling-upgrade (standalone profile route) --------------------
    profile_stage_started = "profile_stage_started"
    profile_stage_completed = "profile_stage_completed"
    profile_progress = "profile_progress"
    profile_cost_estimate = "profile_cost_estimate"
    profile_done = "profile_done"
    profile_error = "profile_error"

    # --- Sample-questions ------------------------------------------------
    sample_questions_ready = "sample_questions.ready"

    # --- Tier-4: orchestration transparency ------------------------------
    stats_context = "stats_context"
    orchestrator_plan = "orchestrator_plan"
    agent_trace = "agent_trace"
    enrichment_trace = "enrichment_trace"
    insight = "insight"
    clarification = "clarification"

    # --- UPPER_CASE aliases (backward-compatible; same values) -----------
    STATUS = "status"
    ERROR = "error"
    METRICS = "metrics"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROFILE_LOADED = "profile_loaded"
    SCHEMA_LINKING_STARTED = "schema_linking_started"
    CANDIDATE_SQLS_GENERATED = "candidate_sqls_generated"
    LITERALS_EXTRACTED = "literals_extracted"
    SEMANTIC_MATCHES = "semantic_matches"
    JOIN_PATHS_ADDED = "join_paths_added"
    LINKED_SCHEMA_FINAL = "linked_schema_final"
    SQL_GENERATED = "sql_generated"
    SQL_EXECUTING = "sql_executing"
    ROWS_RETURNED = "rows_returned"
    ANSWER_GENERATED = "answer_generated"
    PROFILE_STAGE_STARTED = "profile_stage_started"
    PROFILE_STAGE_COMPLETED = "profile_stage_completed"
    PROFILE_PROGRESS = "profile_progress"
    PROFILE_COST_ESTIMATE = "profile_cost_estimate"
    PROFILE_DONE = "profile_done"
    PROFILE_ERROR = "profile_error"


# ---------------------------------------------------------------------------
# Tier-1: lifecycle payloads
# ---------------------------------------------------------------------------


class StatusPayload(BaseModel):
    message: str


class ErrorPayload(BaseModel):
    code: str
    detail: str | None = None


class MetricsPayload(BaseModel):
    """Terminal ``metrics`` chunk for a chat turn.

    Field names mirror ``LLMResponse.input_tokens``/``output_tokens`` (vendored
    ``agents_core.llm.base``) and are what ``routes/chat._extract_metrics_from_chunks``
    reads to populate ``query_metrics.tokens_in``/``tokens_out``. ``prompt_tokens``
    is retained (not renamed to ``input_tokens``) for backward compatibility with
    the existing wire contract and TS types.
    """

    latency_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# Tier-2: generic tool protocol
# ---------------------------------------------------------------------------


class ToolCallPayload(BaseModel):
    tool: str
    arguments: dict[str, object] = Field(default_factory=dict)
    llm_reasoning: str | None = None
    agent: str | None = None


class ToolResultPayload(BaseModel):
    tool: str
    result: object
    visualization: str | None = None
    x_column: str | None = None
    y_column: str | None = None
    agent: str | None = None


# ---------------------------------------------------------------------------
# Tier-3: pipeline transparency payloads
# ---------------------------------------------------------------------------


class ProfileLoadedPayload(BaseModel):
    db_id: str
    table_count: int
    column_count: int
    from_cache: bool


class SchemaLinkingStartedPayload(BaseModel):
    question: str
    db_id: str


class CandidateSQLsGeneratedPayload(BaseModel):
    candidates: list[str]


class LiteralsExtractedPayload(BaseModel):
    literals: list[str]
    matches: dict[str, list[str]]


class SemanticMatchPayload(BaseModel):
    column: str
    score: float


class SemanticMatchesPayload(BaseModel):
    matches: list[SemanticMatchPayload]


class JoinEdgePayload(BaseModel):
    from_: str = Field(alias="from")
    to: str
    kind: str


class JoinPathsAddedPayload(BaseModel):
    edges: list[JoinEdgePayload]


class LinkedSchemaFinalPayload(BaseModel):
    schema_text: str
    linked_tables: list[str]
    linked_columns: list[str]
    column_sources: dict[str, list[str]]
    question_interpretation: str | None = None


class SQLGeneratedPayload(BaseModel):
    sql: str
    iteration: int = 0


# Alias retained to match the plan's naming (``SqlGenerated`` / ``sql_generated``).
SqlGeneratedPayload = SQLGeneratedPayload


class SQLExecutingPayload(BaseModel):
    sql: str


SqlExecutingPayload = SQLExecutingPayload


class RowsReturnedPayload(BaseModel):
    columns: list[str]
    row_count: int
    rows: list[list[object]]
    execution_time_ms: int


class AnswerGeneratedPayload(BaseModel):
    """Final synthesized answer. ``text`` is the complete string (not a delta)."""

    text: str


# ---------------------------------------------------------------------------
# Profiling-upgrade payloads (standalone profile route)
# ---------------------------------------------------------------------------


class ProfileStageStartedPayload(BaseModel):
    """One of: schema | stats | summaries | quirks | lsh | vectors."""

    stage: str
    db_id: str


class ProfileStageCompletedPayload(BaseModel):
    stage: str
    db_id: str
    duration_ms: int
    # ``"skipped"`` when the flag was off; otherwise ``None``.
    note: str | None = None


class ProfileProgressPayload(BaseModel):
    """Mid-stage tick — e.g. ``batch 3/5`` inside summaries or quirks."""

    stage: str
    batch_index: int
    batch_total: int


class ProfileCostEstimatePayload(BaseModel):
    """Emitted once, as the sole chunk of an unconfirmed (cost-gated) request.

    The FE uses ``total_llm_calls`` / ``estimated_seconds`` to render a
    confirmation modal. A second POST with ``confirmed=true`` executes the
    run for real.
    """

    columns: int
    batch_size: int
    total_llm_calls: int
    estimated_seconds: int


class ProfileDonePayload(BaseModel):
    db_id: str
    table_count: int
    column_count: int
    summaries_populated: int


class ProfileErrorPayload(BaseModel):
    db_id: str
    message: str


# ---------------------------------------------------------------------------
# Tier-4: orchestration transparency payloads
# ---------------------------------------------------------------------------


class StatsContextPayload(BaseModel):
    content: str
    groups: list[str] = Field(default_factory=list)


class OrchestratorPlanTask(BaseModel):
    id: str
    agent: str
    task: str
    depends_on: list[str] = Field(default_factory=list)
    category: str = ""


class OrchestratorPlanPayload(BaseModel):
    reasoning: str
    tasks: list[OrchestratorPlanTask] = Field(default_factory=list)


class AgentTracePayload(BaseModel):
    task_id: str
    agent: str
    category: str
    task: str
    depends_on: list[str] = Field(default_factory=list)
    final_sql: str | None = None
    final_answer: str | None = None
    success: bool
    error: str | None = None
    duration_ms: int
    steps: list[dict] = Field(default_factory=list)


class EnrichmentTracePayload(BaseModel):
    source_index: int
    category: str
    question: str
    rationale: str
    final_sql: str | None = None
    final_answer: str | None = None
    success: bool
    duration_ms: int
    steps: list[dict] = Field(default_factory=list)


class InsightPayload(BaseModel):
    content: str
    agent: str
    save_as_insight: bool = False
    insight_summary: str | None = None
    investigation: bool = False


class ClarificationPayload(BaseModel):
    question: str
    skip_allowed: bool = True


class SampleQuestionsReadyPayload(BaseModel):
    db_id: str
    sample_questions: "SampleQuestions"  # forward-ref to sample_questions.types


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

ChunkPayload = Union[
    # Tier-1
    StatusPayload,
    ErrorPayload,
    MetricsPayload,
    # Tier-2
    ToolCallPayload,
    ToolResultPayload,
    # Tier-3
    ProfileLoadedPayload,
    SchemaLinkingStartedPayload,
    CandidateSQLsGeneratedPayload,
    LiteralsExtractedPayload,
    SemanticMatchesPayload,
    JoinPathsAddedPayload,
    LinkedSchemaFinalPayload,
    SQLGeneratedPayload,
    SQLExecutingPayload,
    RowsReturnedPayload,
    AnswerGeneratedPayload,
    # Profiling-upgrade
    ProfileStageStartedPayload,
    ProfileStageCompletedPayload,
    ProfileProgressPayload,
    ProfileCostEstimatePayload,
    ProfileDonePayload,
    ProfileErrorPayload,
    # Tier-4
    StatsContextPayload,
    OrchestratorPlanPayload,
    AgentTracePayload,
    EnrichmentTracePayload,
    InsightPayload,
    ClarificationPayload,
]


class ChatChunk(BaseModel):
    """Envelope sent over the wire as a single ``data:`` line.

    Strict envelope: only ``type``, ``data``, ``conversation_id``, ``timestamp``.
    No top-level flat fields.
    """

    model_config = {"populate_by_name": True}

    type: ChunkType
    data: ChunkPayload | dict[str, object]
    conversation_id: str | None = None
    timestamp: float = Field(default_factory=time)

    def to_json(self) -> str:
        """Serialize the chunk to a JSON string (no SSE framing).

        ``sse_starlette.EventSourceResponse`` handles the ``data:`` prefix and
        trailing double newline itself.
        """
        payload = self.model_dump(mode="json", by_alias=True)
        return json.dumps(payload)


from ..sample_questions.types import SampleQuestions  # noqa: E402
SampleQuestionsReadyPayload.model_rebuild()
