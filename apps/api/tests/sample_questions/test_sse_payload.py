from insightxpert_api.sse.chunks import ChunkType, SampleQuestionsReadyPayload
from insightxpert_api.sample_questions.types import (
    SampleQuestions, SampleQuestionCategory, SampleQuestionsStatus,
)


def test_payload_serializes():
    sq = SampleQuestions(
        status=SampleQuestionsStatus.ok, generated_at=None, model="m",
        categories=[
            SampleQuestionCategory(name="Descriptive", questions=["a?", "b?", "c?"]),
            SampleQuestionCategory(name="Comparative", questions=["d?", "e?", "f?"]),
            SampleQuestionCategory(name="Segmentation", questions=["g?", "h?", "i?"]),
        ],
    )
    p = SampleQuestionsReadyPayload(db_id="t", sample_questions=sq)
    j = p.model_dump_json()
    assert "sample_questions" in j
    assert ChunkType.sample_questions_ready.value == "sample_questions.ready"
