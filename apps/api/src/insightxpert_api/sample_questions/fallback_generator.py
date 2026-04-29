"""Deterministic template-based fallback. Never empty, always schema-grounded."""
from __future__ import annotations

from typing import Sequence

from .schema_features import SchemaFeatures
from .types import CategoryName, SampleQuestionCategory

_PLACEHOLDER_TABLE = "rows"
_PLACEHOLDER_NUMERIC = "value"
_PLACEHOLDER_GROUP = "category"


def _filler(f: SchemaFeatures) -> dict[str, str]:
    return {
        "table": f.largest_table or _PLACEHOLDER_TABLE,
        "metric": f.first_numeric_metric or _PLACEHOLDER_NUMERIC,
        "group": f.top_categorical_column or _PLACEHOLDER_GROUP,
    }


_TEMPLATES: dict[CategoryName, list[str]] = {
    "Descriptive": [
        "How many rows are in {table}?",
        "What is the average {metric} across all {table}?",
        "What is the distribution of {group} values in {table}?",
    ],
    "Comparative": [
        "Which {group} has the highest average {metric} in {table}?",
        "Compare {metric} across {group} values in {table}?",
        "Which {group} value appears most often in {table}?",
    ],
    "Segmentation": [
        "What is the breakdown of {table} by {group}?",
        "How many {table} fall into each {group} group?",
        "What percentage of {table} share each {group}?",
    ],
    "Temporal": [
        "How does the count of {table} change over time?",
        "What is the trend of {metric} over time in {table}?",
        "Which time period has the highest count of {table}?",
    ],
    "Correlation": [
        "Is there a relationship between {group} and {metric} in {table}?",
        "Does {group} affect the average {metric} in {table}?",
        "Which {group} values correlate with high {metric}?",
    ],
}


def generate_fallback(
    categories: Sequence[CategoryName],
    features: SchemaFeatures,
) -> list[SampleQuestionCategory]:
    fill = _filler(features)
    out: list[SampleQuestionCategory] = []
    for cat in categories:
        templates = _TEMPLATES[cat]
        questions = [t.format(**fill) for t in templates]
        out.append(SampleQuestionCategory(name=cat, questions=questions))
    return out
