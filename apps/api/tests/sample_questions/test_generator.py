import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from insightxpert_api.sample_questions.generator import generate_sample_questions
from insightxpert_api.sample_questions.types import SampleQuestionsStatus
from insightxpert_api.vendored.pipeline_core.models.profile import (
    DatabaseProfile, TableProfile, ColumnProfile, ColumnStats,
)


def _profile():
    return DatabaseProfile(db_id="california_schools", tables=[
        TableProfile(name="schools", row_count=100, columns=[
            ColumnProfile(name="County", type="TEXT",
                          stats=ColumnStats(count=100, null_count=0, distinct_count=10)),
            ColumnProfile(name="AvgScrMath", type="INTEGER",
                          stats=ColumnStats(count=100, null_count=0, distinct_count=80)),
        ]),
    ])


def _good_json(profile):
    return json.dumps({
        "categories": [
            {"name": "Descriptive", "questions": [
                "How many rows are in schools?",
                "What is the average AvgScrMath in schools?",
                "What is the distribution of County values?",
            ]},
            {"name": "Comparative", "questions": [
                "Which County has the highest AvgScrMath in schools?",
                "Compare AvgScrMath across County values in schools?",
                "Which County appears most in schools?",
            ]},
            {"name": "Segmentation", "questions": [
                "What is the breakdown of schools by County?",
                "How many schools fall into each County group?",
                "What percentage of schools share each County?",
            ]},
        ]
    })


@pytest.mark.asyncio
async def test_ok_path_returns_status_ok():
    llm = AsyncMock()
    llm.async_generate.return_value = _good_json(_profile())
    out = await generate_sample_questions(_profile(), llm=llm, model_name="gemini-test")
    assert out.status == SampleQuestionsStatus.ok
    assert out.model == "gemini-test"
    assert out.generated_at is not None


@pytest.mark.asyncio
async def test_validation_failure_falls_back():
    llm = AsyncMock()
    llm.async_generate.return_value = '{"categories": []}'
    out = await generate_sample_questions(_profile(), llm=llm, model_name="m")
    assert out.status == SampleQuestionsStatus.fallback
    assert out.model is None
    assert len(out.categories) == 3


@pytest.mark.asyncio
async def test_llm_exception_falls_back():
    llm = AsyncMock()
    llm.async_generate.side_effect = RuntimeError("boom")
    out = await generate_sample_questions(_profile(), llm=llm, model_name="m")
    assert out.status == SampleQuestionsStatus.fallback


@pytest.mark.asyncio
async def test_no_llm_uses_fallback_directly():
    out = await generate_sample_questions(_profile(), llm=None, model_name=None)
    assert out.status == SampleQuestionsStatus.fallback
