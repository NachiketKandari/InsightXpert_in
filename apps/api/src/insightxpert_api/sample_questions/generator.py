"""Generator orchestrator. Composes feature extraction → category selection
→ few-shot retrieval → prompt → LLM → validation → fallback-on-failure.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol

from ..logging import get_logger
from ..vendored.pipeline_core.models.profile import DatabaseProfile
from .category_selector import select_categories
from .fallback_generator import generate_fallback
from .few_shot_retriever import pick_examples
from .prompt_builder import build_prompt
from .schema_features import extract_features
from .types import SampleQuestions, SampleQuestionsStatus
from .validator import ValidationFailure, validate_llm_output

log = get_logger("sample_questions.generator")


class LLMLike(Protocol):
    async def async_generate(self, system: str, user: str) -> str: ...


async def generate_sample_questions(
    profile: DatabaseProfile,
    *,
    llm: LLMLike | None,
    model_name: str | None,
    timeout_s: float = 30.0,
) -> SampleQuestions:
    features = extract_features(profile)
    categories = select_categories(features)
    examples = pick_examples(features, categories, exclude_db_id=profile.db_id)
    log.info(
        "sample_questions.requested",
        extra={"db_id": profile.db_id, "categories": list(categories)},
    )

    if llm is None:
        log.info("sample_questions.fallback_used", extra={"db_id": profile.db_id, "reason": "no_llm"})
        return SampleQuestions(
            status=SampleQuestionsStatus.fallback,
            generated_at=datetime.now(timezone.utc),
            model=None,
            categories=generate_fallback(categories, features),
            few_shot_db_ids=[e.db_id for e in examples],
        )

    system, user = build_prompt(profile, categories, examples)

    try:
        raw = await asyncio.wait_for(llm.async_generate(system, user), timeout=timeout_s)
    except Exception as e:
        log.warning(
            "sample_questions.llm_failed",
            extra={"db_id": profile.db_id, "error": str(e)},
        )
        return SampleQuestions(
            status=SampleQuestionsStatus.fallback,
            generated_at=datetime.now(timezone.utc),
            model=None,
            categories=generate_fallback(categories, features),
            few_shot_db_ids=[e.db_id for e in examples],
        )

    try:
        result = validate_llm_output(raw, categories=categories, profile=profile)
    except ValidationFailure as e:
        log.warning(
            "sample_questions.validation_failed",
            extra={"db_id": profile.db_id, "reason": str(e)},
        )
        return SampleQuestions(
            status=SampleQuestionsStatus.fallback,
            generated_at=datetime.now(timezone.utc),
            model=None,
            categories=generate_fallback(categories, features),
            few_shot_db_ids=[e.db_id for e in examples],
        )

    out = SampleQuestions(
        status=SampleQuestionsStatus.ok,
        generated_at=datetime.now(timezone.utc),
        model=model_name,
        categories=result.categories,
        few_shot_db_ids=[e.db_id for e in examples],
    )
    log.info(
        "sample_questions.generated",
        extra={"db_id": profile.db_id, "status": "ok", "model": model_name},
    )
    return out
