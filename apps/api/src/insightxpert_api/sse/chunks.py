"""SSE chunk taxonomy — the wire contract between pipeline and UI.

Inherits the public-backend taxonomy (``status``, ``sql``, ``tool_call``, ``tool_result``,
``answer``, ``error``, ``metrics``) and extends it with events that expose the text-to-SQL
pipeline's internals, making the "which signals pulled which columns" transparency possible.

Payload shapes here are the SOURCE OF TRUTH for the generated TypeScript types in
``packages/types``. Keep fields precise; avoid ``dict[str, Any]`` unless the shape is genuinely
open-ended (it never should be).
"""

from __future__ import annotations

import json
from enum import Enum
from time import time
from typing import Union

from pydantic import BaseModel, Field


class ChunkType(str, Enum):
    """Closed set of SSE chunk types. FE chunk renderers dispatch on this value."""

    # --- inherited from public backend ------------------------------------
    STATUS = "status"
    SQL = "sql"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ANSWER = "answer"
    ERROR = "error"
    METRICS = "metrics"

    # --- pipeline-internal events (v1 new) --------------------------------
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


# ---------------------------------------------------------------------------
# Payload shapes, one class per chunk type.
# ---------------------------------------------------------------------------


class StatusPayload(BaseModel):
    message: str


class ErrorPayload(BaseModel):
    code: str
    detail: str | None = None


class SQLPayload(BaseModel):
    sql: str


class ToolCallPayload(BaseModel):
    tool: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ToolResultPayload(BaseModel):
    tool: str
    result: object


class AnswerPayload(BaseModel):
    """Streamed-in-progress natural-language answer token/chunk."""

    text: str
    final: bool = False


class MetricsPayload(BaseModel):
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None


class ProfileLoadedPayload(BaseModel):
    db_id: str
    table_count: int
    column_count: int
    from_cache: bool


class SchemaLinkingStartedPayload(BaseModel):
    question: str
    db_id: str


class CandidateSQLsGeneratedPayload(BaseModel):
    candidates: list[str]  # raw 5 candidate SQLs from the single-prompt linker


class LiteralsExtractedPayload(BaseModel):
    """String literals pulled from candidate SQLs + their LSH matches."""

    literals: list[str]
    matches: dict[str, list[str]]  # literal -> ["table.column", ...]


class SemanticMatchPayload(BaseModel):
    column: str  # "table.column"
    score: float


class SemanticMatchesPayload(BaseModel):
    matches: list[SemanticMatchPayload]


class JoinEdgePayload(BaseModel):
    from_: str = Field(alias="from")  # "table.column"
    to: str  # "table.column"
    kind: str  # "declared" | "value_verified" | "bridge"


class JoinPathsAddedPayload(BaseModel):
    edges: list[JoinEdgePayload]


class LinkedSchemaFinalPayload(BaseModel):
    """Final schema handed to the SQL generator, with per-column provenance."""

    schema_text: str
    linked_tables: list[str]
    linked_columns: list[str]  # "table.column"
    column_sources: dict[str, list[str]]  # "table.column" -> ["trial_sql","semantic",...]
    question_interpretation: str | None = None


class SQLGeneratedPayload(BaseModel):
    sql: str
    iteration: int = 0  # 0 = initial, 1+ = refinement rounds


class SQLExecutingPayload(BaseModel):
    sql: str


class RowsReturnedPayload(BaseModel):
    columns: list[str]
    row_count: int
    rows: list[list[object]]
    execution_time_ms: int


class AnswerGeneratedPayload(BaseModel):
    """Final synthesized answer. ``text`` is the complete string (not a delta)."""

    text: str


# Union used for typing convenience; runtime stores `BaseModel | dict`.
ChunkPayload = Union[
    StatusPayload,
    ErrorPayload,
    SQLPayload,
    ToolCallPayload,
    ToolResultPayload,
    AnswerPayload,
    MetricsPayload,
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
]


class ChatChunk(BaseModel):
    """Envelope sent over the wire as a single ``data:`` line."""

    model_config = {"populate_by_name": True}

    type: ChunkType
    data: ChunkPayload | dict[str, object]
    conversation_id: str | None = None
    timestamp: float = Field(default_factory=time)

    def to_sse(self) -> str:
        """Serialize to the ``data: <json>\\n\\n`` SSE frame."""
        payload = self.model_dump(mode="json", by_alias=True)
        return f"data: {json.dumps(payload)}\n\n"
