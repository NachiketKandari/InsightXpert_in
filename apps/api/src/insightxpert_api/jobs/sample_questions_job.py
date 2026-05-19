"""Sample-questions async job.

Wraps the stage with idempotency (skip if already pending/ok/fallback) and
pending-state writeback before kicking off the actual generation. A module-level
semaphore caps concurrent LLM calls so 100 users selecting DBs simultaneously
won't storm the provider.
"""
from __future__ import annotations

import asyncio

from ..logging import get_logger
from ..pipeline.sample_questions_stage import run_sample_questions_for_db
from ..sample_questions import repository as sq_repo
from ..sample_questions.types import SampleQuestionsStatus

log = get_logger("jobs.sample_questions")

# At most 5 concurrent LLM calls for sample-question generation.
# Idempotency checks run BEFORE acquiring the semaphore so already-cached
# or in-flight DBs don't consume a slot.
_sample_questions_semaphore = asyncio.Semaphore(5)


async def run_sample_questions_job(
    *, db_id: str, llm, model_name: str | None, emitter, profile_kind: str = "base",
    session_id: str = "system",
) -> None:
    existing = sq_repo.get_sample_questions(db_id, profile_kind)
    if existing is not None and existing.status in (
        SampleQuestionsStatus.pending,
        SampleQuestionsStatus.ok,
        SampleQuestionsStatus.fallback,
    ):
        log.info(
            "sample_questions.skipped",
            extra={"db_id": db_id, "status": existing.status.value},
        )
        return
    sq_repo.set_pending(db_id, profile_kind)

    async with _sample_questions_semaphore:
        await run_sample_questions_for_db(
            db_id=db_id, llm=llm, model_name=model_name, emitter=emitter,
            profile_kind=profile_kind, session_id=session_id,
        )
