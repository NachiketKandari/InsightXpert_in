from typing import Literal

from pydantic import BaseModel

# Metadata modes matching the paper's Table 1 ablation conditions.
# Controls what column descriptions are injected into SQL generation prompts.
#   none      — raw schema only (column names + types, no descriptions)
#   bird      — BIRD benchmark CSV descriptions (database_description/*.csv)
#   profiling — LLM-generated profile summaries (short_summary per column)
#   fused     — both bird CSV descriptions and LLM profile summaries
MetadataMode = Literal["none", "bird", "profiling", "fused"]


class TestCase(BaseModel):
    question_id: int
    db_id: str
    question: str
    evidence: str = ""
    gold_sql: str
    difficulty: str = "simple"


class EvalResult(BaseModel):
    question_id: int
    db_id: str
    question: str
    evidence: str = ""
    prompt: str = ""
    gold_sql: str
    predicted_sql: str
    difficulty: str = "simple"
    execution_match: bool = False
    execution_match_relaxed: bool = False  # also True when predicted has extra columns but gold data matches
    error: str | None = None
    refined_sql: str | None = None            # SQL after refinement (None if refinement didn't run)
    refinement_iterations: int | None = None  # how many loops ran
    column_sources: dict[str, list[str]] | None = None  # "table.column" → source methods


class RunConfig(BaseModel):
    """Captures the configuration used for a benchmark run."""
    model: str = ""
    thinking_level: str = ""
    metadata_mode: str = "profiling"
    use_linking: bool = True
    linking_mode: str = "multi-variant"  # "multi-variant" | "single-prompt" | "single-prompt-v2" | "single-prompt-clean" | "none"
    use_refinement: bool = True
    use_evidence: bool = True
    use_literal_revision: bool = False
    num_candidates: int = 1
    use_construction_checks: bool = False
    use_intent_classify: bool = False
    use_self_correct: bool = False
    use_dual_schema: bool = False
    use_perfect_linking: bool = False
    use_bridge_join: bool = False
    use_forward_linking: bool = False
    use_pruning: bool = False
    # Profile-variant toggles. metadata_mode continues to control whether raw
    # BIRD text and profiling summaries are injected into the SQL prompt.
    # use_bird_enriched swaps short_summary for the LLM-synthesized
    # bird_enriched_summary (built offline). use_quirks gates the quirks render
    # block (enum labels, aliases, type-mismatch notes, semantic hint).
    use_bird_enriched: bool = False
    use_quirks: bool = True
    use_few_shot: bool = False
    benchmark: str = "mini_dev"


class EvalReport(BaseModel):
    total: int
    correct: int
    accuracy: float
    correct_relaxed: int = 0
    accuracy_relaxed: float = 0.0
    by_difficulty: dict[str, dict[str, int]] = {}
    run_config: RunConfig | None = None
    results: list[EvalResult] = []
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
