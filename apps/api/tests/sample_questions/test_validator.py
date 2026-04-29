import json
import pytest
from insightxpert_api.sample_questions.validator import (
    ValidationFailure, validate_llm_output,
)
from insightxpert_api.vendored.pipeline_core.models.profile import (
    DatabaseProfile, TableProfile, ColumnProfile, ColumnStats,
)


def _profile():
    return DatabaseProfile(db_id="t", tables=[
        TableProfile(name="schools", row_count=10, columns=[
            ColumnProfile(name="County", type="TEXT",
                          stats=ColumnStats(count=10, null_count=0, distinct_count=5)),
            ColumnProfile(name="AvgScrMath", type="INTEGER",
                          stats=ColumnStats(count=10, null_count=0, distinct_count=10)),
        ]),
    ])


def _good():
    return {
        "categories": [
            {"name": "Descriptive", "questions": [
                "How many rows are in schools?",
                "What is the average AvgScrMath?",
                "What is the distribution of County?",
            ]},
            {"name": "Comparative", "questions": [
                "Which County has the highest AvgScrMath?",
                "Compare AvgScrMath across County values?",
                "Which County appears most often?",
            ]},
            {"name": "Segmentation", "questions": [
                "What is the breakdown of schools by County?",
                "How many schools per County?",
                "What percentage of schools share each County?",
            ]},
        ]
    }


def test_happy_path_passes():
    out = validate_llm_output(
        json.dumps(_good()), categories=("Descriptive", "Comparative", "Segmentation"),
        profile=_profile(),
    )
    assert len(out.categories) == 3


def test_invalid_json_raises():
    with pytest.raises(ValidationFailure, match="parse"):
        validate_llm_output("not json", categories=("Descriptive","Comparative","Segmentation"), profile=_profile())


def test_wrong_category_count_raises():
    payload = _good()
    payload["categories"].pop()
    with pytest.raises(ValidationFailure, match="categories"):
        validate_llm_output(json.dumps(payload), categories=("Descriptive","Comparative","Segmentation"), profile=_profile())


def test_question_without_question_mark_raises():
    payload = _good()
    payload["categories"][0]["questions"][0] = "How many rows are in schools."
    with pytest.raises(ValidationFailure, match="question_mark"):
        validate_llm_output(json.dumps(payload), categories=("Descriptive","Comparative","Segmentation"), profile=_profile())


def test_hallucinated_column_raises():
    payload = _good()
    payload["categories"][0]["questions"][0] = "How many ImaginaryColumn are there?"
    with pytest.raises(ValidationFailure, match="schema_token"):
        validate_llm_output(json.dumps(payload), categories=("Descriptive","Comparative","Segmentation"), profile=_profile())


def test_near_duplicate_questions_raise():
    payload = _good()
    payload["categories"][0]["questions"] = [
        "What is the average AvgScrMath in schools?",
        "What is the average AvgScrMath in schools today?",
        "What is the distribution of County?",
    ]
    with pytest.raises(ValidationFailure, match="duplicate"):
        validate_llm_output(json.dumps(payload), categories=("Descriptive","Comparative","Segmentation"), profile=_profile())
