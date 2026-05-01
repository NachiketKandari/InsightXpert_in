"""Text-to-SQL pipeline: Stage Protocol + default orchestrator."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .pipeline import Pipeline
from .stage import PipelineContext, Stage

if TYPE_CHECKING:
    from ..config import Settings
    from ..services.database_service import DatabaseService
    from ..services.profile_service import ProfileService


def _vendored_prompt(*parts: str) -> str:
    """Resolve a prompt path inside the vendored tree relative to this package.

    Using ``__file__`` keeps imports CWD-independent — the caller (tests, FastAPI
    worker, CLI) doesn't need to run from the repo root.
    """
    # Pipeline package is at insightxpert_api/pipeline/__init__.py; the vendored
    # tree is a sibling at insightxpert_api/vendored/pipeline_core/.
    base = Path(__file__).resolve().parent.parent / "vendored" / "pipeline_core"
    return str(base.joinpath(*parts))


def _project_prompt(*parts: str) -> str:
    """Resolve a prompt path under apps/api/src/insightxpert_api/prompts/.

    Used for prompts that are project-original (not vendored from
    public/InsightXpert). Sibling helper to ``_vendored_prompt``.
    """
    base = Path(__file__).resolve().parent.parent / "prompts"
    return str(base.joinpath(*parts))


PipelineMode = Literal["linked", "full_schema"]


def default_pipeline(
    settings: "Settings",
    db_svc: "DatabaseService",
    prof_svc: "ProfileService",
    *,
    pipeline_mode: PipelineMode = "linked",
) -> Pipeline:
    """Compose the 6-stage v1 text-to-SQL pipeline.

    ``pipeline_mode`` controls the second stage (schema → SQL-gen handoff):
      * ``"linked"`` — ``SchemaLinkerStage`` (default). Emits the trial-SQL
        / literal-LSH / semantic / join-path / linked-schema chunks.
      * ``"full_schema"`` — ``FullSchemaStage``. Bypasses the linker and
        hands the SQL generator the full ``SchemaFormatter`` render with
        FK tags and per-table ``Foreign Keys:`` blocks.
    """
    from ..llm.gemini import GeminiLLM
    from .executor_stage import SqlExecutorStage
    from .full_schema_stage import FullSchemaStage
    from .generator_stage import SqlGeneratorStage
    from .linker_stage import SchemaLinkerStage
    from .profiler_stage import ProfilerStage
    from .refiner_stage import SqlRefinerStage
    from .synthesizer_stage import AnswerSynthesizerStage
    from .validator_stage import SqlValidatorStage

    llm = GeminiLLM(
        api_key=settings.gemini_api_key,
        model=settings.gemini_chat_model,
        embed_model=settings.gemini_embed_model,
    )
    schema_stage: Any
    if pipeline_mode == "full_schema":
        schema_stage = FullSchemaStage(db_svc=db_svc)
    else:
        schema_stage = SchemaLinkerStage(
            llm=llm,
            prompt_path=_vendored_prompt("prompts", "single_prompt_linking_clean.j2"),
        )
    pipeline = Pipeline([
        ProfilerStage(db_svc=db_svc, prof_svc=prof_svc, llm=llm),
        schema_stage,
        SqlGeneratorStage(
            llm=llm,
            # SF15: switched from the greenfield-only 11-line prompts_clean
            # stub to the production 163-line prompt with CoT, JOIN guidance,
            # and rule includes that ships with Private/InsightXpert.
            prompt_path=_vendored_prompt("prompts", "sql_generation.j2"),
        ),
        SqlValidatorStage(),
        SqlExecutorStage(db_svc=db_svc, row_limit=settings.sql_row_limit),
        SqlRefinerStage(
            llm=llm,
            max_iters=settings.max_refinement_iterations,
            db_svc=db_svc,
            prompt_path=_vendored_prompt("prompts", "refine_sql.j2"),
        ),
        AnswerSynthesizerStage(
            llm=llm,
            prompt_path=_project_prompt("answer_synthesizer.j2"),
        ),
    ])
    # Expose the adapter so the route layer can read per-turn token totals
    # (``llm.input_tokens_used`` / ``llm.output_tokens_used``) after the
    # pipeline finishes and include them in the terminal ``metrics`` chunk.
    pipeline.llm = llm  # type: ignore[attr-defined]
    return pipeline


__all__ = ["Pipeline", "PipelineContext", "Stage", "default_pipeline"]
