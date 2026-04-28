"""Read/write the ``database_profiles.sample_questions`` JSONB column."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update

from ..db.engine import get_engine
from ..profiling.table import database_profiles
from .types import (
    SampleQuestions, SampleQuestionCategory, SampleQuestionsStatus,
)


def get_sample_questions(db_id: str, profile_kind: str = "base") -> SampleQuestions | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(database_profiles.c.sample_questions).where(
                database_profiles.c.db_id == db_id,
                database_profiles.c.profile_kind == profile_kind,
            )
        ).first()
    if row is None or row[0] is None:
        return None
    raw = row[0]
    if isinstance(raw, str):
        raw = json.loads(raw)
    return SampleQuestions.model_validate(raw)


def set_sample_questions(
    db_id: str,
    sq: SampleQuestions,
    profile_kind: str = "base",
) -> None:
    payload = sq.model_dump(mode="json")
    with get_engine().begin() as conn:
        conn.execute(
            update(database_profiles)
            .where(
                database_profiles.c.db_id == db_id,
                database_profiles.c.profile_kind == profile_kind,
            )
            .values(sample_questions=payload)
        )


def set_pending(db_id: str, profile_kind: str = "base") -> None:
    pending = SampleQuestions(
        status=SampleQuestionsStatus.pending,
        generated_at=datetime.now(timezone.utc),
        model=None,
        categories=[
            SampleQuestionCategory(name="Descriptive", questions=["…", "…", "…"]),
            SampleQuestionCategory(name="Comparative", questions=["…", "…", "…"]),
            SampleQuestionCategory(name="Segmentation", questions=["…", "…", "…"]),
        ],
    )
    set_sample_questions(db_id, pending, profile_kind)
