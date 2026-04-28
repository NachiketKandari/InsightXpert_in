"""Adaptive 3-of-5 category selection driven by schema features.

Always returns exactly 3 distinct categories. Pure-Python.
"""
from __future__ import annotations

from .schema_features import SchemaFeatures
from .types import CategoryName


def select_categories(f: SchemaFeatures) -> tuple[CategoryName, CategoryName, CategoryName]:
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
        _fallback: tuple[CategoryName, ...] = ("Comparative", "Segmentation", "Correlation")
        for c in _fallback:
            if c != slot1 and c != slot2:
                slot3 = c
                break
    return slot1, slot2, slot3
