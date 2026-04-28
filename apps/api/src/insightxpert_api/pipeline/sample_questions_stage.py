"""Async sample-questions stage. Invoked post-profile by the job runner.

Loads the profile, calls the generator, persists, and (optionally) emits an
SSE event so live UIs update without a poll.
"""
from __future__ import annotations

from typing import Protocol

from ..logging import get_logger
from ..sample_questions import repository as sq_repo
from ..sample_questions.generator import generate_sample_questions
from ..sample_questions.types import SampleQuestions, SampleQuestionsStatus
from ..services.profile_service import ProfileService
from ..sse.chunks import ChunkType, SampleQuestionsReadyPayload  # added in Task 15
from ..sse.emitter import EventEmitter

log = get_logger("pipeline.sample_questions_stage")


class _SinglePromptLLM(Protocol):
    async def async_generate(self, prompt: str) -> str: ...


def _adapt_llm(llm: _SinglePromptLLM | None):
    """Adapt GeminiLLM (single-prompt) to the (system, user) interface generator expects."""
    if llm is None:
        return None

    class _Adapter:
        async def async_generate(self, system: str, user: str) -> str:
            return await llm.async_generate(f"{system}\n\n{user}")

    return _Adapter()


async def run_sample_questions_for_db(
    *,
    db_id: str,
    llm,
    model_name: str | None,
    emitter: EventEmitter | None,
    profile_kind: str = "base",
    session_id: str = "system",
) -> SampleQuestions:
    prof_svc = ProfileService()
    profile = prof_svc.load(session_id=session_id, db_id=db_id, profile_kind=profile_kind)

    if profile is None:
        from ..sample_questions.fallback_generator import generate_fallback
        from ..sample_questions.schema_features import SchemaFeatures
        log.warning("sample_questions.profile_unavailable", extra={"db_id": db_id})
        empty = SchemaFeatures(
            has_temporal=False, has_categorical=False, has_numeric_metric=False,
            has_geo=False, has_relations=False, table_count=0, total_columns=0,
            total_rows=0, largest_table=None, first_numeric_metric=None,
            top_categorical_column=None,
        )
        sq = SampleQuestions(
            status=SampleQuestionsStatus.failed,
            generated_at=None, model=None,
            categories=generate_fallback(("Descriptive", "Comparative", "Segmentation"), empty),
            error="profile_unavailable",
        )
        try:
            sq_repo.set_sample_questions(db_id, sq, profile_kind)
        except Exception:
            pass
        return sq

    sq = await generate_sample_questions(profile, llm=_adapt_llm(llm), model_name=model_name)
    sq_repo.set_sample_questions(db_id, sq, profile_kind)

    if emitter is not None:
        await emitter.emit(
            ChunkType.sample_questions_ready,
            SampleQuestionsReadyPayload(db_id=db_id, sample_questions=sq),
        )

    return sq
