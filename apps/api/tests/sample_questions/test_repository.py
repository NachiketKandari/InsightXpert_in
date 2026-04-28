import pytest

from insightxpert_api.sample_questions.repository import (
    get_sample_questions, set_sample_questions, set_pending,
)
from insightxpert_api.sample_questions.types import (
    SampleQuestions, SampleQuestionCategory, SampleQuestionsStatus,
)
from insightxpert_api.profiling import repository as profiles_repo


@pytest.fixture
def seeded_profile(fresh_db):
    profiles_repo.upsert(
        db_id="california_schools", profile_kind="base",
        owner_user_id="u1", generated_by="u1",
        profile_json='{"db_id":"california_schools","tables":[]}',
    )
    return "california_schools"


def test_get_returns_none_when_unset(seeded_profile):
    assert get_sample_questions(seeded_profile) is None


def test_set_then_get_roundtrip(seeded_profile):
    sq = SampleQuestions(
        status=SampleQuestionsStatus.ok,
        generated_at=None, model="m",
        categories=[
            SampleQuestionCategory(name="Descriptive", questions=["a?", "b?", "c?"]),
            SampleQuestionCategory(name="Comparative", questions=["d?", "e?", "f?"]),
            SampleQuestionCategory(name="Segmentation", questions=["g?", "h?", "i?"]),
        ],
    )
    set_sample_questions(seeded_profile, sq)
    out = get_sample_questions(seeded_profile)
    assert out is not None
    assert out.status == SampleQuestionsStatus.ok
    assert len(out.categories) == 3


def test_set_pending_idempotent(seeded_profile):
    set_pending(seeded_profile)
    set_pending(seeded_profile)
    out = get_sample_questions(seeded_profile)
    assert out.status == SampleQuestionsStatus.pending
