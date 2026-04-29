from datetime import datetime
import pytest
from pydantic import ValidationError

from insightxpert_api.sample_questions.types import (
    SampleQuestions,
    SampleQuestionCategory,
    SampleQuestionsStatus,
)


def test_valid_sample_questions_roundtrip():
    obj = SampleQuestions(
        status=SampleQuestionsStatus.ok,
        generated_at=datetime(2026, 4, 28),
        model="gemini-3.1-flash-lite-preview",
        categories=[
            SampleQuestionCategory(name="Descriptive", questions=["a?", "b?", "c?"]),
            SampleQuestionCategory(name="Comparative", questions=["d?", "e?", "f?"]),
            SampleQuestionCategory(name="Temporal", questions=["g?", "h?", "i?"]),
        ],
        few_shot_db_ids=["california_schools"],
    )
    assert obj.status == "ok"
    assert len(obj.categories) == 3
    assert obj.error is None


def test_must_have_exactly_three_categories():
    with pytest.raises(ValidationError):
        SampleQuestions(
            status=SampleQuestionsStatus.ok,
            generated_at=datetime(2026, 4, 28),
            model="m",
            categories=[
                SampleQuestionCategory(name="Descriptive", questions=["a?", "b?", "c?"]),
            ],
        )


def test_each_category_has_exactly_three_questions():
    with pytest.raises(ValidationError):
        SampleQuestionCategory(name="Descriptive", questions=["a?", "b?"])


def test_invalid_category_name_rejected():
    with pytest.raises(ValidationError):
        SampleQuestionCategory(name="Nonsense", questions=["a?", "b?", "c?"])
