"""Execute due automations.

This is the one place where:
    1. We find automations whose ``next_run_at <= now`` (or target a specific id).
    2. Resolve the DB file + execute the SQL chain against it.
    3. Evaluate triggers against the final result.
    4. Persist an ``automation_runs`` row.
    5. If triggers fired → create + dispatch a notification.

Embedded and external schedulers both delegate here.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from ..db.connector import DatabaseConnector
from ..db.engine import get_background_engine
from ..logging import get_logger
from ..services.database_service import DatabaseService
from . import notifications as notif_module
from . import repository
from .evaluator import TriggerEvaluator
from .models import RunBatchItem, RunBatchResult
from .service import AutomationService

log = get_logger("automations.runner")

# In-process re-entrancy guard to prevent overlapping runs of the same
# automation within one worker. Cross-replica safety is handled by
# repository.claim_due_automations advancing next_run_at atomically.
_locks: dict[str, asyncio.Lock] = {}

# Max concurrent automations in one batch. Bounded to keep DB / thread-pool
# pressure sane — a single tick fanning out to 100 automations must not
# swamp the process. Tunable via follow-up config.
_BATCH_CONCURRENCY = 8


@dataclass(frozen=True)
class LlmUsage:
    """Captured LLM token snapshot for deferred recording.

    The runner captures this at LLM-call time but writes the metrics row
    only after the automation_runs row is persisted, so ``source_ref_id``
    can point at the persisted run id (a stable foreign-key-ish handle)
    instead of guessing via a (user_id, created_at) window join.
    """

    input_tokens: int
    output_tokens: int
    model: str
    feature: str  # "automation.run" today; future: per-LLM-call sources


def _lock_for(automation_id: str) -> asyncio.Lock:
    lock = _locks.get(automation_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[automation_id] = lock
    return lock


def _resolve_db_path(db_svc: DatabaseService, db_id: str) -> str | None:
    """Resolve a db_id against the bundled registry. Returns a local path or None."""
    # DatabaseService.resolve takes a session_id; bundled DBs ignore it. Using
    # the db_id itself works because bundled resolution is session-independent.
    ref = db_svc.resolve(session_id=db_id, db_id=db_id)
    if ref is None:
        return None
    return ref.local_path


def _run_sql(path: str, sql: str, row_limit: int = 1000) -> dict[str, Any]:
    """Execute ``sql`` against the sqlite file at ``path``."""
    result = DatabaseConnector(path, row_limit=row_limit).execute(sql)
    return {"columns": result.columns, "rows": result.rows}


async def _execute_one(
    app: FastAPI | None,
    automation_id: str,
) -> RunBatchItem:
    lock = _lock_for(automation_id)
    async with lock:
        # Phase 1.2 — read LLM token counters before/after the run so we can
        # attribute any ai_sql generation spend to this automation. Today
        # automation runs don't invoke the LLM inline (sql_queries are
        # pre-generated via /generate-sql), but we wire the emission path now
        # so future per-run regeneration lands with zero extra plumbing.
        llm_for_run = getattr(app.state, "llm", None) if app is not None else None
        tokens_before_in = int(
            getattr(llm_for_run, "input_tokens_used", 0) or 0
        )
        tokens_before_out = int(
            getattr(llm_for_run, "output_tokens_used", 0) or 0
        )
        auto_for_usage: dict[str, Any] | None = None
        # Persisted automation_runs.id, set the moment a run row is inserted.
        # The deferred LLM-usage write below uses this as ``source_ref_id`` so
        # the metric is joinable to a real persisted row, not a brittle
        # (user_id, created_at) window.
        persisted_run_id: str | None = None
        _bg = get_background_engine()

        try:
            auto = repository.get_automation(automation_id, _engine=_bg)
            auto_for_usage = auto
            if auto is None:
                return RunBatchItem(
                    automation_id=automation_id, status="skipped",
                    error="not_found",
                )
            if not auto.get("is_active"):
                return RunBatchItem(
                    automation_id=automation_id, status="skipped",
                    error="inactive",
                )

            log.info(
                "automation.run_started",
                automation_id=automation_id,
                db_id=auto.get("db_id"),
                owner_user_id=auto.get("owner_user_id"),
            )

            try:
                sql_queries = json.loads(auto.get("sql_queries_json") or "[]")
            except json.JSONDecodeError:
                sql_queries = []
            if not sql_queries:
                _err_run = repository.insert_run({
                    "automation_id": automation_id,
                    "status": "error",
                    "error_message": "no sql queries configured",
                }, _engine=_bg)
                persisted_run_id = _err_run["id"]
                AutomationService().mark_run_completed(automation_id, int(time.time()), _engine=_bg)
                log.error(
                    "automation.run_error",
                    automation_id=automation_id,
                    reason="no_sql_queries",
                )
                return RunBatchItem(
                    automation_id=automation_id, status="error",
                    error="no sql queries",
                )

            # Resolve DB path
            db_path: str | None
            if app is not None and hasattr(app.state, "db_service"):
                db_svc: DatabaseService = app.state.db_service
                db_path = _resolve_db_path(db_svc, auto["db_id"])
            else:
                # Fallback — construct a DatabaseService from settings.
                from ..config import get_settings
                from ..storage import build_store

                settings = get_settings()
                db_svc = DatabaseService(
                    bundled_dir=settings.bundled_dbs_dir,
                    store=build_store(settings),
                )
                db_path = _resolve_db_path(db_svc, auto["db_id"])

            if db_path is None:
                _err_run = repository.insert_run({
                    "automation_id": automation_id,
                    "status": "error",
                    "error_message": f"db not found: {auto['db_id']}",
                }, _engine=_bg)
                persisted_run_id = _err_run["id"]
                AutomationService().mark_run_completed(automation_id, int(time.time()), _engine=_bg)
                log.error(
                    "automation.run_error",
                    automation_id=automation_id,
                    reason="db_not_found",
                    db_id=auto["db_id"],
                )
                return RunBatchItem(
                    automation_id=automation_id, status="error",
                    error=f"db_not_found:{auto['db_id']}",
                )

            start = time.perf_counter()
            step_results: list[dict[str, Any]] = []
            try:
                for sql in sql_queries:
                    step_results.append(
                        await asyncio.to_thread(_run_sql, db_path, sql)
                    )
            except Exception as exc:  # noqa: BLE001
                execution_ms = int((time.perf_counter() - start) * 1000)
                _err_run = repository.insert_run({
                    "automation_id": automation_id,
                    "status": "error",
                    "error_message": str(exc),
                    "execution_time_ms": execution_ms,
                }, _engine=_bg)
                persisted_run_id = _err_run["id"]
                AutomationService().mark_run_completed(automation_id, int(time.time()), _engine=_bg)
                log.error(
                    "automation.run_error",
                    automation_id=automation_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    exc_info=True,
                )
                return RunBatchItem(
                    automation_id=automation_id, status="error", error=str(exc)
                )

            execution_ms = int((time.perf_counter() - start) * 1000)
            final_result = step_results[-1]
            row_count = len(final_result.get("rows", []))
            result_to_store = (
                final_result if len(step_results) == 1
                else {**final_result, "step_results": step_results}
            )

            # Gather trigger conditions + previous result for change_detection
            trigger_rows = repository.list_triggers(automation_id, _engine=_bg)
            conditions = [
                {
                    "type": t["type"],
                    "column": t["column"],
                    "operator": t["operator"],
                    "value": t["value"],
                    "change_percent": t["change_percent"],
                    "scope": t["scope"],
                    "nl_text": t["nl_text"],
                }
                for t in trigger_rows
            ]

            previous_result: dict | None = None
            if conditions:
                prev_runs = repository.list_runs(automation_id, limit=1, _engine=_bg)
                if prev_runs:
                    raw = prev_runs[0].get("result_json")
                    if isinstance(raw, str):
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, dict):
                                previous_result = {
                                    "columns": parsed.get("columns", []),
                                    "rows": parsed.get("rows", []),
                                }
                        except json.JSONDecodeError:
                            pass

            if not conditions:
                run = repository.insert_run({
                    "automation_id": automation_id,
                    "status": "success",
                    "result_json": json.dumps(result_to_store),
                    "row_count": row_count,
                    "execution_time_ms": execution_ms,
                }, _engine=_bg)
                persisted_run_id = run["id"]
                AutomationService().mark_run_completed(automation_id, int(time.time()), _engine=_bg)
                log.info(
                    "automation.run_completed",
                    automation_id=automation_id,
                    run_id=run["id"],
                    status="success",
                    row_count=row_count,
                    execution_time_ms=execution_ms,
                    triggers_fired=0,
                )
                return RunBatchItem(
                    automation_id=automation_id, status="success",
                    execution_time_ms=execution_ms,
                )

            evaluator = TriggerEvaluator()
            trigger_results = evaluator.evaluate(conditions, final_result, previous_result)
            any_fired = evaluator.any_fired(trigger_results)
            status = "success" if any_fired else "no_trigger"

            # Emit one structured event per fired trigger so operators can grep
            # for "trigger_fired" without joining to the runs table.
            for tr in trigger_results:
                if tr.get("fired"):
                    log.info(
                        "automation.trigger_fired",
                        automation_id=automation_id,
                        trigger_type=tr.get("type"),
                        actual_value=tr.get("actual_value"),
                    )

            run = repository.insert_run({
                "automation_id": automation_id,
                "status": status,
                "result_json": json.dumps(result_to_store),
                "row_count": row_count,
                "execution_time_ms": execution_ms,
                "triggers_fired_json": json.dumps(trigger_results),
            }, _engine=_bg)
            persisted_run_id = run["id"]
            AutomationService().mark_run_completed(automation_id, int(time.time()), _engine=_bg)

            triggers_fired_count = sum(1 for t in trigger_results if t.get("fired"))
            log.info(
                "automation.run_completed",
                automation_id=automation_id,
                run_id=run["id"],
                status=status,
                row_count=row_count,
                execution_time_ms=execution_ms,
                triggers_fired=triggers_fired_count,
            )

            if any_fired:
                fired_msgs = [r["message"] for r in trigger_results if r.get("fired")]
                notif = notif_module.create(
                    user_id=auto["owner_user_id"],
                    automation_id=automation_id,
                    run_id=run["id"],
                    title=f"Alert: {auto['name']}",
                    message="\n".join(fired_msgs),
                    severity="warning",
                    _engine=_bg,
                )
                if app is not None:
                    try:
                        await notif_module.dispatch(app, auto["owner_user_id"], notif)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("automation.notif_dispatch_failed", error=str(exc))

            return RunBatchItem(
                automation_id=automation_id,
                status=status,
                execution_time_ms=execution_ms,
            )
        finally:
            # Phase 1.2 / Track 1.3 — emit a usage row when LLM tokens were
            # consumed during this run. We capture the delta into a local
            # ``LlmUsage`` snapshot, then write the metrics row exactly once
            # using the persisted automation_runs.id as ``source_ref_id``.
            # That replaces the previous (user_id, created_at) window-join
            # trick and gives us a stable join key for cost analytics.
            try:
                from ..config import get_settings
                from ..metrics.llm_usage import record_llm_usage

                _settings = get_settings()
                tokens_in_delta = (
                    int(getattr(llm_for_run, "input_tokens_used", 0) or 0)
                    - tokens_before_in
                )
                tokens_out_delta = (
                    int(getattr(llm_for_run, "output_tokens_used", 0) or 0)
                    - tokens_before_out
                )
                usage: LlmUsage | None = None
                if (
                    (tokens_in_delta > 0 or tokens_out_delta > 0)
                    and auto_for_usage is not None
                ):
                    usage = LlmUsage(
                        input_tokens=tokens_in_delta,
                        output_tokens=tokens_out_delta,
                        model=getattr(
                            llm_for_run, "model", _settings.gemini_chat_model
                        ),
                        feature="automation.run",
                    )

                if usage is not None and auto_for_usage is not None:
                    # source_ref_id prefers the persisted run id; falls back
                    # to automation_id only when no run row was written
                    # (extremely rare — only if persistence raised before
                    # any insert_run call).
                    record_llm_usage(
                        source="automation",
                        provider="gemini",
                        model=usage.model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        user_id=str(auto_for_usage.get("owner_user_id") or ""),
                        source_ref_id=persisted_run_id or automation_id,
                        db_id=auto_for_usage.get("db_id"),
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "automation.usage_emit_failed",
                    extra={"automation_id": automation_id, "error": str(exc)},
                )


async def run_due_automations(
    app: FastAPI | None = None,
    *,
    now: int | None = None,
    automation_id: str | None = None,
) -> RunBatchResult:
    """Execute one or many automations.

    * ``automation_id`` set → run that single automation (manual trigger /
      scheduled per-job callback).
    * Otherwise → pick up all active automations with ``next_run_at <= now``.
      Batch execution is parallelized via ``asyncio.gather`` bounded by a
      ``Semaphore`` so a single slow automation doesn't stall the rest.
    """
    now_ts = now if now is not None else int(time.time())
    if automation_id is not None:
        item = await _execute_one(app, automation_id)
        return RunBatchResult(ran=[item])

    # Atomically claim rows so concurrent calls (e.g. another replica) do
    # not double-fire the same automation. The claim advances next_run_at
    # past the due predicate; mark_run_completed below resets it to the
    # real cron tick after each run.
    due = await asyncio.to_thread(
        repository.claim_due_automations,
        now_ts=now_ts,
        batch_size=_BATCH_CONCURRENCY * 4,
    )
    if not due:
        return RunBatchResult(ran=[])

    # Fresh semaphore per batch — we never want cross-batch serialization and
    # a module-level semaphore would make testing under pytest-asyncio awkward
    # (each test gets its own event loop).
    semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)

    # Resolve the executor via module lookup so tests that
    # ``monkeypatch.setattr(runner, "_execute_one", ...)`` take effect.
    import sys

    _module = sys.modules[__name__]

    async def _gated(aid: str) -> RunBatchItem:
        async with semaphore:
            return await _module._execute_one(app, aid)

    results = await asyncio.gather(
        *(_gated(a["id"]) for a in due),
        return_exceptions=True,
    )
    ran: list[RunBatchItem] = []
    for item in results:
        if isinstance(item, BaseException):
            log.error(
                "automation.batch_exception",
                error=str(item),
                error_type=type(item).__name__,
            )
            continue
        ran.append(item)
    return RunBatchResult(ran=ran)


__all__ = ["run_due_automations"]
