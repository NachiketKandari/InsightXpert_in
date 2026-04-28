"""Adaptive 3-of-5 category selection driven by schema features.

Always returns exactly 3 distinct categories. Pure-Python.
"""
from __future__ import annotations

from typing import Literal, Tuple

from .schema_features import SchemaFeatures

CategoryName = Literal[
    "Descriptive", "Comparative", "Temporal", "Segmentation", "Correlation"
]


def select_categories(f: SchemaFeatures) -> Tuple[CategoryName, CategoryName, CategoryName]:
    slot1: CategoryName = "Descriptive"
    slot2: CategoryName = "Comparative" if f.has_categorical else "Segmentation"

    slot3: CategoryName
    if f.has_temporal:
        slot3 = "Temporal"
    elif f.has_categorical and slot2 != "Segmentation":
        slot3 = "Segmentation"
    elif f.has_numeric_metric and f.has_categorical:
        slot3 = "Correlation"
    else:
        slot3 = "Comparative"

    if slot3 == slot2:
        # avoid duplicate; substitute with first not-yet-used
        for c in ("Comparative", "Segmentation", "Correlation"):
            if c != slot1 and c != slot2:
                slot3 = c  # type: ignore[assignment]
                break
    return slot1, slot2, slot3
