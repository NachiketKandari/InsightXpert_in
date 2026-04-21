"""Pydantic request/response models for the automations feature.

Ported from ``public/InsightXpert/backend/src/insightxpert/automations/models.py``
with these transformations:
    * ``slope`` trigger type removed — ``TriggerCondition.type`` is restricted to
      one of 4 values; no ``slope_window`` field.
    * ``db_id`` is required on Create + surfaced on Read.
    * ``workflow_graph`` accepted as pass-through dict; never interpreted.
    * ``org_id`` removed everywhere — single-tenant.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SCHEDULE_PRESETS: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}

TriggerType = Literal[
    "threshold", "row_count", "change_detection", "column_expression"
]
TriggerOperator = Literal["gt", "gte", "lt", "lte", "eq", "ne"]
TriggerScope = Literal["any_row", "all_rows"]


class TriggerCondition(BaseModel):
    """One trigger rule. Only fields relevant to ``type`` are used downstream."""

    type: TriggerType
    column: str | None = None
    operator: TriggerOperator | None = None
    value: float | None = None
    change_percent: float | None = None
    scope: TriggerScope | None = None
    nl_text: str | None = None


class TriggerResult(BaseModel):
    condition: TriggerCondition
    fired: bool
    actual_value: float | None = None
    message: str = ""


def _validate_cron(expr: str) -> str:
    """Validate a cron expression via croniter. Raises ValueError on failure."""
    from croniter import croniter

    expr = expr.strip()
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron expression must have exactly 5 fields")
    if not croniter.is_valid(expr):
        raise ValueError(f"invalid cron expression: {expr!r}")
    return expr


class CreateAutomationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    nl_query: str
    sql_queries: list[str] = Field(default_factory=list)
    db_id: str = Field(min_length=1, max_length=255)
    schedule_preset: str | None = None
    cron_expression: str | None = None
    trigger_conditions: list[TriggerCondition] = Field(default_factory=list)
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    workflow_graph: dict | None = None  # C2 pass-through; not interpreted

    @field_validator("sql_queries")
    @classmethod
    def _non_empty_queries(cls, v: list[str]) -> list[str]:
        cleaned = [q.strip() for q in v if q and q.strip()]
        return cleaned

    def resolved_cron(self) -> str:
        if self.schedule_preset:
            cron = SCHEDULE_PRESETS.get(self.schedule_preset)
            if not cron:
                raise ValueError(
                    f"Unknown schedule preset: {self.schedule_preset}. "
                    f"Valid: {', '.join(SCHEDULE_PRESETS)}"
                )
            return cron
        if self.cron_expression:
            return _validate_cron(self.cron_expression)
        raise ValueError("either schedule_preset or cron_expression is required")


class UpdateAutomationRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    nl_query: str | None = None
    sql_queries: list[str] | None = None
    db_id: str | None = None
    cron_expression: str | None = None
    schedule_preset: str | None = None
    trigger_conditions: list[TriggerCondition] | None = None
    workflow_graph: dict | None = None
    is_active: bool | None = None

    def resolved_cron(self) -> str | None:
        if self.schedule_preset:
            cron = SCHEDULE_PRESETS.get(self.schedule_preset)
            if not cron:
                raise ValueError(
                    f"Unknown schedule preset: {self.schedule_preset}"
                )
            return cron
        if self.cron_expression:
            return _validate_cron(self.cron_expression)
        return None


class CompileTriggerRequest(BaseModel):
    nl_text: str
    available_columns: list[str] | None = None


class GenerateSQLRequest(BaseModel):
    prompt: str
    db_id: str | None = None


class GenerateSQLResponse(BaseModel):
    sql: str
    explanation: str | None = None


class AutomationResponse(BaseModel):
    id: str
    name: str
    description: str | None
    nl_query: str
    sql_queries: list[str]
    db_id: str
    cron_expression: str
    trigger_conditions: list[TriggerCondition]
    is_active: bool
    owner_user_id: str
    source_conversation_id: str | None
    source_message_id: str | None
    workflow_graph: dict | None = None
    last_run_at: int | None
    next_run_at: int | None
    created_at: int
    updated_at: int


class AutomationRunResponse(BaseModel):
    id: str
    automation_id: str
    status: str
    result_json: dict | None = None
    row_count: int | None
    execution_time_ms: int | None
    triggers_fired: list[TriggerResult] | None = None
    error_message: str | None
    created_at: int


class CreateTriggerTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    conditions: list[TriggerCondition]


class UpdateTriggerTemplateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: list[TriggerCondition] | None = None


class TriggerTemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None
    conditions: list[TriggerCondition]
    owner_user_id: str
    created_at: int
    updated_at: int


class NotificationResponse(BaseModel):
    id: str
    user_id: str
    automation_id: str | None
    run_id: str | None
    title: str
    message: str
    severity: Literal["info", "success", "warning", "error"]
    is_read: bool
    automation_name: str | None = None
    created_at: int


class RunBatchItem(BaseModel):
    automation_id: str
    status: str
    execution_time_ms: int | None = None
    error: str | None = None


class RunBatchResult(BaseModel):
    ran: list[RunBatchItem] = Field(default_factory=list)


__all__ = [
    "SCHEDULE_PRESETS",
    "TriggerCondition",
    "TriggerResult",
    "CreateAutomationRequest",
    "UpdateAutomationRequest",
    "CompileTriggerRequest",
    "GenerateSQLRequest",
    "GenerateSQLResponse",
    "AutomationResponse",
    "AutomationRunResponse",
    "CreateTriggerTemplateRequest",
    "UpdateTriggerTemplateRequest",
    "TriggerTemplateResponse",
    "NotificationResponse",
    "RunBatchItem",
    "RunBatchResult",
]
