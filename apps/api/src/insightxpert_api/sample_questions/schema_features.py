"""Deterministic feature-vector extraction from a ``DatabaseProfile``.

Pure-Python — no LLM, no DB. Run this *before* the LLM call so the prompt is
constrained by what the schema actually supports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..vendored.pipeline_core.models.profile import DatabaseProfile, ColumnProfile

_TEMPORAL_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
_TEMPORAL_NAME_RE = re.compile(r"(_at|_date|_time|year|month|day)$", re.I)
_GEO_NAME_RE = re.compile(
    r"^(country|state|city|region|zip|postal|lat|lon|latitude|longitude)$", re.I
)
_NUMERIC_TYPES = {"INTEGER", "INT", "REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"}


@dataclass(frozen=True)
class SchemaFeatures:
    has_temporal: bool
    has_categorical: bool
    has_numeric_metric: bool
    has_geo: bool
    has_relations: bool
    table_count: int
    total_columns: int
    total_rows: int
    largest_table: str | None
    first_numeric_metric: str | None
    top_categorical_column: str | None


def _is_temporal(c: ColumnProfile) -> bool:
    if c.type and c.type.upper() in _TEMPORAL_TYPES:
        return True
    return bool(_TEMPORAL_NAME_RE.search(c.name))


def _is_categorical(c: ColumnProfile, row_count: int) -> bool:
    if not c.type or "TEXT" not in c.type.upper() and "CHAR" not in c.type.upper():
        return False
    distinct = c.stats.distinct_count
    if distinct == 0 or distinct > 50:
        return False
    return row_count >= 10 * distinct


def _is_numeric_metric(c: ColumnProfile) -> bool:
    return any(t in (c.type or "").upper() for t in _NUMERIC_TYPES)


def _is_geo(c: ColumnProfile) -> bool:
    return bool(_GEO_NAME_RE.match(c.name))


def _has_fk_hints(profile: DatabaseProfile) -> bool:
    for t in profile.tables:
        for c in t.columns:
            if c.quirks.fk_alias:
                return True
    return False


def extract_features(profile: DatabaseProfile) -> SchemaFeatures:
    has_temporal = False
    has_categorical = False
    has_numeric_metric = False
    has_geo = False
    table_count = len(profile.tables)
    total_columns = 0
    total_rows = 0
    largest_table: str | None = None
    largest_rows = -1
    first_numeric_metric: str | None = None
    top_categorical_column: str | None = None
    top_categorical_rows = -1

    for t in profile.tables:
        total_columns += len(t.columns)
        total_rows += t.row_count
        if t.row_count > largest_rows:
            largest_rows = t.row_count
            largest_table = t.name
        for c in t.columns:
            if _is_temporal(c):
                has_temporal = True
            if _is_categorical(c, t.row_count):
                has_categorical = True
                if t.row_count > top_categorical_rows:
                    top_categorical_rows = t.row_count
                    top_categorical_column = c.name
            if _is_numeric_metric(c):
                has_numeric_metric = True
                if first_numeric_metric is None:
                    first_numeric_metric = c.name
            if _is_geo(c):
                has_geo = True

    return SchemaFeatures(
        has_temporal=has_temporal,
        has_categorical=has_categorical,
        has_numeric_metric=has_numeric_metric,
        has_geo=has_geo,
        has_relations=_has_fk_hints(profile),
        table_count=table_count,
        total_columns=total_columns,
        total_rows=total_rows,
        largest_table=largest_table,
        first_numeric_metric=first_numeric_metric,
        top_categorical_column=top_categorical_column,
    )
