import pytest
from unittest.mock import AsyncMock, patch

from insightxpert_api.jobs.sample_questions_job import run_sample_questions_job
from insightxpert_api.sample_questions import repository as sq_repo
from insightxpert_api.profiling import repository as profiles_repo


@pytest.fixture
def seeded(fresh_db):
    profiles_repo.upsert(
        db_id="t", profile_kind="base", owner_user_id="u", generated_by="u",
        profile_json='{"db_id":"t","tables":[{"name":"x","row_count":1,"columns":[{"name":"y","type":"INTEGER","stats":{"count":1,"null_count":0,"distinct_count":1}}]}]}',
    )


@pytest.mark.asyncio
async def test_enqueue_skips_when_already_pending(seeded):
    sq_repo.set_pending("t")
    with patch(
        "insightxpert_api.jobs.sample_questions_job.run_sample_questions_for_db",
        AsyncMock(),
    ) as run:
        await run_sample_questions_job(db_id="t", llm=None, model_name=None, emitter=None)
        run.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_runs_when_not_pending(seeded):
    with patch(
        "insightxpert_api.jobs.sample_questions_job.run_sample_questions_for_db",
        AsyncMock(),
    ) as run:
        await run_sample_questions_job(db_id="t", llm=None, model_name=None, emitter=None)
        run.assert_called_once()
