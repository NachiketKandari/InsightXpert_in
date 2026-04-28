"""Pydantic models for per-DB sample questions.

Lives outside the vendored ``DatabaseProfile`` model. Persisted as a sibling
JSONB column on ``database_profiles`` (see Task 10 migration).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

CategoryName = Literal[
    "Descriptive", "Comparative", "Temporal", "Segmentation", "Correlation"
]


class SampleQuestionsStatus(str, Enum):
    ok = "ok"
    fallback = "fallback"
    pending = "pending"
    failed = "failed"


class SampleQuestionCategory(BaseModel):
    name: CategoryName
    questions: list[str] = Field(min_length=3, max_length=3)


class SampleQuestions(BaseModel):
    status: SampleQuestionsStatus
    generated_at: datetime | None = None
    model: str | None = None
    categories: list[SampleQuestionCategory] = Field(min_length=3, max_length=3)
    few_shot_db_ids: list[str] = Field(default_factory=list)
    error: str | None = None
