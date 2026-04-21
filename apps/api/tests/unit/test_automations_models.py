"""Unit tests for Pydantic models + cron validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from insightxpert_api.automations.models import (
    SCHEDULE_PRESETS,
    CreateAutomationRequest,
    TriggerCondition,
)


def test_trigger_type_rejects_slope():
    with pytest.raises(ValidationError):
        TriggerCondition(type="slope", operator="gt", value=1)


def test_trigger_type_accepts_supported():
    for t in ("threshold", "row_count", "change_detection", "column_expression"):
        tc = TriggerCondition(type=t)
        assert tc.type == t


def test_trigger_operator_rejects_unknown():
    with pytest.raises(ValidationError):
        TriggerCondition(type="threshold", operator="gtt")


def test_create_requires_db_id():
    with pytest.raises(ValidationError):
        CreateAutomationRequest(
            name="x",
            nl_query="q",
            sql_queries=["SELECT 1"],
            cron_expression="* * * * *",
        )


def test_create_resolved_cron_from_preset():
    req = CreateAutomationRequest(
        name="x",
        nl_query="q",
        sql_queries=["SELECT 1"],
        db_id="toxicology",
        schedule_preset="hourly",
    )
    assert req.resolved_cron() == SCHEDULE_PRESETS["hourly"]


def test_create_resolved_cron_from_expression():
    req = CreateAutomationRequest(
        name="x",
        nl_query="q",
        sql_queries=["SELECT 1"],
        db_id="toxicology",
        cron_expression="0 * * * *",
    )
    assert req.resolved_cron() == "0 * * * *"


def test_create_rejects_invalid_cron():
    req = CreateAutomationRequest(
        name="x",
        nl_query="q",
        sql_queries=["SELECT 1"],
        db_id="toxicology",
        cron_expression="not a cron",
    )
    with pytest.raises(ValueError):
        req.resolved_cron()


def test_create_requires_either_preset_or_cron():
    req = CreateAutomationRequest(
        name="x",
        nl_query="q",
        sql_queries=["SELECT 1"],
        db_id="toxicology",
    )
    with pytest.raises(ValueError):
        req.resolved_cron()


def test_create_preset_bad_key_raises():
    req = CreateAutomationRequest(
        name="x",
        nl_query="q",
        sql_queries=["SELECT 1"],
        db_id="toxicology",
        schedule_preset="yearly",
    )
    with pytest.raises(ValueError):
        req.resolved_cron()


def test_create_cleans_empty_sql_queries():
    req = CreateAutomationRequest(
        name="x",
        nl_query="q",
        sql_queries=["SELECT 1", "  ", ""],
        db_id="toxicology",
        schedule_preset="daily",
    )
    assert req.sql_queries == ["SELECT 1"]


def test_schedule_presets_shape():
    assert set(SCHEDULE_PRESETS) == {"hourly", "daily", "weekly", "monthly"}
    for expr in SCHEDULE_PRESETS.values():
        assert len(expr.split()) == 5
