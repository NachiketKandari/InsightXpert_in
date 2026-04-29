"""Pick one few-shot example per chosen category, ranked by feature similarity.

The bank is curated and committed at ``fixtures/bird_examples.json``. Selection
is a simple Hamming-distance over the boolean feature vector — small bank,
exact match dominates, no need for embeddings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Iterable, Sequence

from .schema_features import SchemaFeatures
from .types import CategoryName


@dataclass(frozen=True)
class FewShotExample:
    db_id: str
    category: CategoryName
    features: dict[str, bool]
    question: str


@lru_cache(maxsize=None)
def load_bank() -> list[FewShotExample]:
    text = resources.files(__package__).joinpath("fixtures/bird_examples.json").read_text()
    raw = json.loads(text)
    return [
        FewShotExample(
            db_id=e["db_id"],
            category=e["category"],
            features=e["features"],
            question=e["question"],
        )
        for e in raw
    ]


_BOOL_FIELDS = (
    "has_temporal", "has_categorical", "has_numeric_metric",
    "has_geo", "has_relations",
)


def _hamming(target: SchemaFeatures, ex: FewShotExample) -> int:
    score = 0
    for f in _BOOL_FIELDS:
        if getattr(target, f) != ex.features.get(f, False):
            score += 1
    return score


def _pick_for_category(
    bank: Iterable[FewShotExample],
    target: SchemaFeatures,
    category: CategoryName,
    exclude_db_id: str | None,
) -> FewShotExample | None:
    candidates = [
        e for e in bank
        if e.category == category and (exclude_db_id is None or e.db_id != exclude_db_id)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda e: _hamming(target, e))


def pick_examples(
    target: SchemaFeatures,
    categories: Sequence[CategoryName],
    exclude_db_id: str | None,
) -> list[FewShotExample]:
    bank = load_bank()
    out: list[FewShotExample] = []
    for cat in categories:
        ex = _pick_for_category(bank, target, cat, exclude_db_id)
        if ex is None:
            # last-resort: any example with the closest distance, regardless of category,
            # rewritten with the requested category. Used only when bank is missing this category.
            anyex = min(bank, key=lambda e: _hamming(target, e))
            ex = FewShotExample(
                db_id=anyex.db_id, category=cat, features=anyex.features,
                question=anyex.question,
            )
        out.append(ex)
    return out
