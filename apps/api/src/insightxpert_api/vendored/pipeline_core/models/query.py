from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    db_id: str
    evidence: str = ""


class CandidateSQL(BaseModel):
    sql: str
    prompt: str = ""  # full prompt sent to the LLM that produced this candidate
    reasoning: str = ""
    confidence: float = 1.0


class LinkedField(BaseModel):
    table: str
    column: str


class FewShotExampleRef(BaseModel):
    """Snapshot of the retrieved few-shot example, surfaced for prompt rendering."""
    question: str
    gold_sql: str
    similarity: float = 0.0


class SchemaLinkResult(BaseModel):
    linked_tables: list[str]
    linked_columns: list[LinkedField]
    literals_found: list[str] = []
    variant_contributions: dict[str, int] = {}
    schema_text: str
    question_interpretation: str = ""
    column_sources: dict[str, list[str]] = {}  # "table.column" → list of source methods
    few_shot_example: FewShotExampleRef | None = None


class RefinedSQL(BaseModel):
    sql: str
    changes: list[str] = []        # one entry per refinement loop (the feedback that triggered it)
    iterations: int = 0            # 0 = passthrough (no change needed)
    original_sql: str = ""         # candidate SQL before any refinement
    final_error: str | None = None # error after last iteration (None = fixed or passthrough)


class QueryResult(BaseModel):
    sql: str
    rows: list[list] = []
    columns: list[str] = []
    error: str | None = None


class QueryResponse(BaseModel):
    request: QueryRequest
    candidate: CandidateSQL | None = None
    refined: RefinedSQL | None = None
    result: QueryResult | None = None
    linked_schema: "SchemaLinkResult | None" = None  # Phase 4: pruned schema from SchemaLinker
    # Multi-candidate voting (populated only when num_candidates > 1)
    all_candidates: list[CandidateSQL] | None = None
    all_results: list[QueryResult] | None = None
    vote_method: str | None = None
