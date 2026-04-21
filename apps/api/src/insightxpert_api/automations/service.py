"""Business logic for automations, runs, templates, and notifications.

Single-tenant (no ``org_id``). Owner-or-admin scoping enforced here; routes
simply pass ``CurrentUser`` through. All reads/writes go through the
repository layer; this module never opens a SQLAlchemy ``Session``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from croniter import croniter

from . import repository
from .models import (
    SCHEDULE_PRESETS,
    CreateAutomationRequest,
    TriggerCondition,
    UpdateAutomationRequest,
)

logger = logging.getLogger("insightxpert_api.automations.service")


class AutomationError(Exception):
    pass


class NotFoundError(AutomationError):
    pass


class ForbiddenError(AutomationError):
    pass


def _now() -> int:
    return int(time.time())


def _uuid() -> str:
    return str(uuid.uuid4())


def _next_run_at(cron_expression: str, from_ts: int | None = None) -> int:
    base = from_ts if from_ts is not None else _now()
    itr = croniter(cron_expression, start_time=base)
    return int(itr.get_next(float))


def _require_owner_or_admin(
    resource: dict[str, Any],
    user_id: str,
    is_admin: bool,
    owner_field: str = "owner_user_id",
) -> None:
    if is_admin:
        return
    if resource.get(owner_field) == user_id:
        return
    raise ForbiddenError("forbidden")


# ---------------------------------------------------------------------------
# AutomationService
# ---------------------------------------------------------------------------


class AutomationService:
    """CRUD + lookups. Does not execute triggers (see runner.py)."""

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _hydrate(auto: dict[str, Any]) -> dict[str, Any]:
        """Attach trigger_conditions + sql_queries + parsed workflow_graph."""
        triggers = repository.list_triggers(auto["id"])
        trigger_conditions = [
            {
                "type": t["type"],
                "column": t["column"],
                "operator": t["operator"],
                "value": t["value"],
                "change_percent": t["change_percent"],
                "scope": t["scope"],
                "nl_text": t["nl_text"],
            }
            for t in triggers
        ]
        try:
            sql_queries = json.loads(auto.get("sql_queries_json") or "[]")
            if not isinstance(sql_queries, list):
                sql_queries = []
        except json.JSONDecodeError:
            sql_queries = []

        workflow_graph: dict | None = None
        raw_wf = auto.get("workflow_graph_json")
        if raw_wf:
            try:
                workflow_graph = json.loads(raw_wf)
            except json.JSONDecodeError:
                workflow_graph = None

        return {
            "id": auto["id"],
            "name": auto["name"],
            "description": auto.get("description"),
            "nl_query": auto["nl_query"],
            "sql_queries": sql_queries,
            "db_id": auto["db_id"],
            "cron_expression": auto["cron_expression"],
            "trigger_conditions": trigger_conditions,
            "is_active": bool(auto["is_active"]),
            "owner_user_id": auto["owner_user_id"],
            "source_conversation_id": auto.get("source_conversation_id"),
            "source_message_id": auto.get("source_message_id"),
            "workflow_graph": workflow_graph,
            "last_run_at": auto.get("last_run_at"),
            "next_run_at": auto.get("next_run_at"),
            "created_at": auto["created_at"],
            "updated_at": auto["updated_at"],
        }

    # ---- CRUD -----------------------------------------------------------

    def create(
        self, req: CreateAutomationRequest, owner_user_id: str
    ) -> dict[str, Any]:
        if not req.sql_queries:
            raise AutomationError("at least one SQL query is required")
        cron = req.resolved_cron()

        auto_id = _uuid()
        now = _now()
        workflow_json = (
            json.dumps(req.workflow_graph) if req.workflow_graph else None
        )

        repository.insert_automation(
            {
                "id": auto_id,
                "name": req.name,
                "description": req.description,
                "nl_query": req.nl_query,
                "sql_queries_json": json.dumps(req.sql_queries),
                "db_id": req.db_id,
                "cron_expression": cron,
                "is_active": True,
                "owner_user_id": owner_user_id,
                "source_conversation_id": req.source_conversation_id,
                "source_message_id": req.source_message_id,
                "workflow_graph_json": workflow_json,
                "last_run_at": None,
                "next_run_at": _next_run_at(cron, now),
                "created_at": now,
                "updated_at": now,
            }
        )
        repository.replace_triggers(
            auto_id,
            [tc.model_dump() for tc in req.trigger_conditions],
        )
        row = repository.get_automation(auto_id)
        assert row is not None
        return self._hydrate(row)

    def get(
        self, automation_id: str, user_id: str, is_admin: bool
    ) -> dict[str, Any]:
        row = repository.get_automation(automation_id)
        if row is None:
            raise NotFoundError("automation not found")
        _require_owner_or_admin(row, user_id, is_admin)
        return self._hydrate(row)

    def list_for_user(
        self, user_id: str, is_admin: bool
    ) -> list[dict[str, Any]]:
        rows = (
            repository.list_automations(owner_user_id=None) if is_admin
            else repository.list_automations(owner_user_id=user_id)
        )
        return [self._hydrate(r) for r in rows]

    def update(
        self,
        automation_id: str,
        req: UpdateAutomationRequest,
        user_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        existing = repository.get_automation(automation_id)
        if existing is None:
            raise NotFoundError("automation not found")
        _require_owner_or_admin(existing, user_id, is_admin)

        values: dict[str, Any] = {}
        if req.name is not None:
            values["name"] = req.name
        if req.description is not None:
            values["description"] = req.description
        if req.nl_query is not None:
            values["nl_query"] = req.nl_query
        if req.sql_queries is not None:
            cleaned = [q.strip() for q in req.sql_queries if q and q.strip()]
            if not cleaned:
                raise AutomationError("at least one SQL query is required")
            values["sql_queries_json"] = json.dumps(cleaned)
        if req.db_id is not None:
            values["db_id"] = req.db_id
        if req.is_active is not None:
            values["is_active"] = req.is_active
        if req.workflow_graph is not None:
            values["workflow_graph_json"] = json.dumps(req.workflow_graph)

        new_cron = req.resolved_cron()
        if new_cron is not None:
            values["cron_expression"] = new_cron
            values["next_run_at"] = _next_run_at(new_cron)

        if values:
            repository.update_automation(automation_id, values)

        if req.trigger_conditions is not None:
            repository.replace_triggers(
                automation_id,
                [tc.model_dump() for tc in req.trigger_conditions],
            )

        row = repository.get_automation(automation_id)
        assert row is not None
        return self._hydrate(row)

    def delete(
        self, automation_id: str, user_id: str, is_admin: bool
    ) -> None:
        existing = repository.get_automation(automation_id)
        if existing is None:
            raise NotFoundError("automation not found")
        _require_owner_or_admin(existing, user_id, is_admin)
        repository.delete_automation(automation_id)

    def toggle(
        self, automation_id: str, user_id: str, is_admin: bool
    ) -> dict[str, Any]:
        existing = repository.get_automation(automation_id)
        if existing is None:
            raise NotFoundError("automation not found")
        _require_owner_or_admin(existing, user_id, is_admin)
        new_state = not bool(existing["is_active"])
        values: dict[str, Any] = {"is_active": new_state}
        if new_state:
            # re-arm next_run_at when reactivating
            values["next_run_at"] = _next_run_at(existing["cron_expression"])
        repository.update_automation(automation_id, values)
        row = repository.get_automation(automation_id)
        assert row is not None
        return self._hydrate(row)

    def mark_run_completed(
        self, automation_id: str, last_run_at: int
    ) -> None:
        existing = repository.get_automation(automation_id)
        if existing is None:
            return
        repository.update_automation(
            automation_id,
            {
                "last_run_at": last_run_at,
                "next_run_at": _next_run_at(
                    existing["cron_expression"], last_run_at
                ),
            },
        )

    # ---- runs ------------------------------------------------------------

    def list_runs(
        self,
        automation_id: str,
        user_id: str,
        is_admin: bool,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        existing = repository.get_automation(automation_id)
        if existing is None:
            raise NotFoundError("automation not found")
        _require_owner_or_admin(existing, user_id, is_admin)
        return [
            self._run_to_dict(r) for r in repository.list_runs(automation_id, limit)
        ]

    def get_run(
        self,
        automation_id: str,
        run_id: str,
        user_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        existing = repository.get_automation(automation_id)
        if existing is None:
            raise NotFoundError("automation not found")
        _require_owner_or_admin(existing, user_id, is_admin)
        run = repository.get_run(run_id)
        if run is None or run["automation_id"] != automation_id:
            raise NotFoundError("run not found")
        return self._run_to_dict(run)

    @staticmethod
    def _run_to_dict(run: dict[str, Any]) -> dict[str, Any]:
        result_json = run.get("result_json")
        if isinstance(result_json, str):
            try:
                result_json = json.loads(result_json)
            except json.JSONDecodeError:
                result_json = None

        triggers_fired = run.get("triggers_fired_json")
        if isinstance(triggers_fired, str):
            try:
                triggers_fired = json.loads(triggers_fired)
            except json.JSONDecodeError:
                triggers_fired = None

        return {
            "id": run["id"],
            "automation_id": run["automation_id"],
            "status": run["status"],
            "result_json": result_json,
            "row_count": run.get("row_count"),
            "execution_time_ms": run.get("execution_time_ms"),
            "triggers_fired": triggers_fired,
            "error_message": run.get("error_message"),
            "created_at": run["created_at"],
        }


# ---------------------------------------------------------------------------
# TriggerTemplateService
# ---------------------------------------------------------------------------


class TriggerTemplateService:
    @staticmethod
    def _hydrate(tpl: dict[str, Any]) -> dict[str, Any]:
        try:
            conditions = json.loads(tpl.get("conditions_json") or "[]")
        except json.JSONDecodeError:
            conditions = []
        return {
            "id": tpl["id"],
            "name": tpl["name"],
            "description": tpl.get("description"),
            "conditions": conditions,
            "owner_user_id": tpl["owner_user_id"],
            "created_at": tpl["created_at"],
            "updated_at": tpl["updated_at"],
        }

    def create(
        self,
        *,
        name: str,
        description: str | None,
        conditions: list[TriggerCondition],
        owner_user_id: str,
    ) -> dict[str, Any]:
        tpl_id = _uuid()
        now = _now()
        repository.insert_template(
            {
                "id": tpl_id,
                "name": name,
                "description": description,
                "conditions_json": json.dumps(
                    [c.model_dump() for c in conditions]
                ),
                "owner_user_id": owner_user_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        row = repository.get_template(tpl_id)
        assert row is not None
        return self._hydrate(row)

    def list_for_user(
        self, user_id: str, is_admin: bool
    ) -> list[dict[str, Any]]:
        rows = (
            repository.list_templates(owner_user_id=None) if is_admin
            else repository.list_templates(owner_user_id=user_id)
        )
        return [self._hydrate(r) for r in rows]

    def get(
        self, template_id: str, user_id: str, is_admin: bool
    ) -> dict[str, Any]:
        row = repository.get_template(template_id)
        if row is None:
            raise NotFoundError("template not found")
        _require_owner_or_admin(row, user_id, is_admin)
        return self._hydrate(row)

    def update(
        self,
        template_id: str,
        *,
        name: str | None,
        description: str | None,
        conditions: list[TriggerCondition] | None,
        user_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        existing = repository.get_template(template_id)
        if existing is None:
            raise NotFoundError("template not found")
        _require_owner_or_admin(existing, user_id, is_admin)
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if conditions is not None:
            values["conditions_json"] = json.dumps(
                [c.model_dump() for c in conditions]
            )
        repository.update_template(template_id, values)
        row = repository.get_template(template_id)
        assert row is not None
        return self._hydrate(row)

    def delete(
        self, template_id: str, user_id: str, is_admin: bool
    ) -> None:
        existing = repository.get_template(template_id)
        if existing is None:
            raise NotFoundError("template not found")
        _require_owner_or_admin(existing, user_id, is_admin)
        repository.delete_template(template_id)


# ---------------------------------------------------------------------------
# NotificationService
# ---------------------------------------------------------------------------


class NotificationService:
    @staticmethod
    def _hydrate(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "automation_id": row.get("automation_id"),
            "run_id": row.get("run_id"),
            "title": row["title"],
            "message": row["message"],
            "severity": row["severity"],
            "is_read": bool(row["is_read"]),
            "automation_name": row.get("automation_name"),
            "created_at": row["created_at"],
        }

    def list_for_user(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return [
            self._hydrate(r)
            for r in repository.list_notifications(
                user_id, unread_only=unread_only, limit=limit
            )
        ]

    def unread_count(self, user_id: str) -> int:
        return repository.count_unread(user_id)

    def mark_read(self, notification_id: str, user_id: str) -> bool:
        return repository.mark_notification_read(notification_id, user_id)

    def mark_all_read(self, user_id: str) -> int:
        return repository.mark_all_notifications_read(user_id)


__all__ = [
    "AutomationService",
    "TriggerTemplateService",
    "NotificationService",
    "AutomationError",
    "NotFoundError",
    "ForbiddenError",
    "SCHEDULE_PRESETS",
]
