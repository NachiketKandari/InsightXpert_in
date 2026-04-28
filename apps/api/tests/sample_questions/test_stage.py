from unittest.mock import AsyncMock, patch
import pytest

from insightxpert_api.pipeline.sample_questions_stage import run_sample_questions_for_db
from insightxpert_api.sample_questions import repository as sq_repo
from insightxpert_api.sample_questions.types import SampleQuestionsStatus
from insightxpert_api.profiling import repository as profiles_repo


@pytest.fixture
def seeded(fresh_db):
    profiles_repo.upsert(
        db_id="t", profile_kind="base", owner_user_id="u", generated_by="u",
        profile_json='{"db_id":"t","tables":[{"name":"x","row_count":1,"columns":[{"name":"y","type":"INTEGER","stats":{"count":1,"null_count":0,"distinct_count":1}}]}]}',
    )


@pytest.mark.asyncio
async def test_stage_writes_fallback_when_no_llm(seeded):
    await run_sample_questions_for_db(db_id="t", llm=None, model_name=None, emitter=None)
    sq = sq_repo.get_sample_questions("t")
    assert sq is not None
    assert sq.status == SampleQuestionsStatus.fallback


@pytest.mark.asyncio
async def test_stage_emits_sse_when_emitter_provided(seeded):
    emitter = AsyncMock()
    await run_sample_questions_for_db(db_id="t", llm=None, model_name=None, emitter=emitter)
    emitter.emit.assert_called()  # at least one event with sample_questions.ready
