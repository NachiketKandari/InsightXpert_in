"""Strict LLM-output validator. No partial repair — fail or pass.

On failure callers fall back to the deterministic template generator.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Sequence

from pydantic import ValidationError

from ..vendored.pipeline_core.models.profile import DatabaseProfile
from .types import CategoryName, SampleQuestionCategory


class ValidationFailure(Exception):
    pass


@dataclass(frozen=True)
class ValidationResult:
    categories: list[SampleQuestionCategory]


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _schema_tokens(profile: DatabaseProfile) -> set[str]:
    toks: set[str] = set()
    for t in profile.tables:
        toks.add(t.name.lower())
        for c in t.columns:
            toks.add(c.name.lower())
    return toks


def _question_tokens(q: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(q)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def validate_llm_output(
    raw: str,
    categories: Sequence[CategoryName],
    profile: DatabaseProfile,
) -> ValidationResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValidationFailure(f"parse: {e}") from e

    cats = data.get("categories")
    if not isinstance(cats, list) or len(cats) != 3:
        raise ValidationFailure("categories: expected 3")
    actual_names = [c.get("name") for c in cats]
    if tuple(actual_names) != tuple(categories):
        raise ValidationFailure(f"categories: order/names mismatch (got {actual_names})")

    parsed: list[SampleQuestionCategory] = []
    for c in cats:
        try:
            parsed.append(SampleQuestionCategory.model_validate(c))
        except ValidationError as e:
            raise ValidationFailure(f"shape: {e}") from e

    schema_toks = _schema_tokens(profile)
    all_questions: list[str] = []
    for cat in parsed:
        for q in cat.questions:
            if not q.endswith("?"):
                raise ValidationFailure(f"question_mark: {q!r}")
            if len(q) > 200:
                raise ValidationFailure(f"length: {q!r}")
            qtoks = _question_tokens(q)
            if not (qtoks & schema_toks):
                raise ValidationFailure(f"schema_token: no schema name in {q!r}")
            all_questions.append(q)

    for i in range(len(all_questions)):
        for j in range(i + 1, len(all_questions)):
            if _jaccard(_question_tokens(all_questions[i]), _question_tokens(all_questions[j])) > 0.6:
                raise ValidationFailure(
                    f"duplicate: {all_questions[i]!r} ~ {all_questions[j]!r}"
                )

    return ValidationResult(categories=parsed)
