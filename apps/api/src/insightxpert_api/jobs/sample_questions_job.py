"""Sample-questions async job.

Wraps the stage with idempotency (skip if already pending) and pending-state
writeback before kicking off the actual generation.
"""
from __future__ import annotations

from ..logging import get_logger
from ..pipeline.sample_questions_stage import run_sample_questions_for_db
from ..sample_questions import repository as sq_repo
from ..sample_questions.types import SampleQuestionsStatus

log = get_logger("jobs.sample_questions")


async def run_sample_questions_job(
    *, db_id: str, llm, model_name: str | None, emitter, profile_kind: str = "base",
    session_id: str = "system",
) -> None:
    existing = sq_repo.get_sample_questions(db_id, profile_kind)
    if existing is not None and existing.status == SampleQuestionsStatus.pending:
        log.info("sample_questions.skipped_already_pending", extra={"db_id": db_id})
        return
    sq_repo.set_pending(db_id, profile_kind)
    await run_sample_questions_for_db(
        db_id=db_id, llm=llm, model_name=model_name, emitter=emitter,
        profile_kind=profile_kind, session_id=session_id,
    )
