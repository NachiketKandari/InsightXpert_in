"""Automations CRUD + trigger templates + compile / generate helpers.

All endpoints require an authenticated caller. Owner-or-admin scoping is
enforced at the service layer. The whole router is gated in ``main.py`` behind
``settings.automations_enabled``.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.current_user import CurrentUser, get_current_user
from ..automations import ai_sql as ai_sql_mod
from ..automations import nl_trigger as nl_trigger_mod
from ..automations import runner
from ..automations.models import (
    CompileTriggerRequest,
    CreateAutomationRequest,
    CreateTriggerTemplateRequest,
    GenerateSQLRequest,
    UpdateAutomationRequest,
    UpdateTriggerTemplateRequest,
)
from ..automations.service import (
    AutomationError,
    AutomationService,
    ForbiddenError,
    NotFoundError,
    NotificationService,
    TriggerTemplateService,
)
from ..db.connector import FORBIDDEN_SQL_RE

log = logging.getLogger("insightxpert_api.routes.automations")

router = APIRouter(prefix="/api/v1/automations", tags=["automations"])
templates_router = APIRouter(
    prefix="/api/v1/automations/templates", tags=["automations-templates"]
)


def _svc() -> AutomationService:
    return AutomationService()


def _tpl_svc() -> TriggerTemplateService:
    return TriggerTemplateService()


def _is_admin(user: CurrentUser) -> bool:
    return user.role == "admin"


def _resolve_llm(request: Request):
    """Return an LLM instance. Uses app.state.llm if set (tests inject there),
    otherwise constructs a GeminiLLM from settings."""
    llm = getattr(request.app.state, "llm", None)
    if llm is not None:
        return llm
    from ..config import get_settings
    from ..llm import GeminiLLM

    settings = get_settings()
    return GeminiLLM(
        api_key=settings.gemini_api_key,
        model=settings.gemini_chat_model,
        embed_model=settings.gemini_embed_model,
    )


def _validate_sql_queries(queries: list[str]) -> None:
    if not queries:
        raise HTTPException(status_code=400, detail="at least one SQL query is required")
    for i, sql in enumerate(queries):
        s = (sql or "").strip()
        if not s:
            raise HTTPException(status_code=400, detail=f"step {i+1}: empty SQL")
        if FORBIDDEN_SQL_RE.search(s):
            raise HTTPException(
                status_code=400,
                detail=f"step {i+1}: forbidden SQL (only SELECT allowed)",
            )
        stripped = s.rstrip(";")
        if ";" in stripped:
            raise HTTPException(
                status_code=400,
                detail=f"step {i+1}: multi-statement SQL is not allowed",
            )
        if not sqlite3.complete_statement(stripped + ";"):
            raise HTTPException(
                status_code=400,
                detail=f"step {i+1}: invalid or incomplete SQL",
            )


def _not_found_or_forbidden(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------


@router.post("/compile-trigger")
async def compile_trigger(
    body: CompileTriggerRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    llm = _resolve_llm(request)
    # Phase 1.2 — snapshot token counters before the LLM call so the emission
    # fires even on parse-fallback or provider-error paths. Runs in a
    # try/finally so any raised exception still gets recorded.
    _tokens_before_in = int(getattr(llm, "input_tokens_used", 0) or 0)
    _tokens_before_out = int(getattr(llm, "output_tokens_used", 0) or 0)
    try:
        return await nl_trigger_mod.compile_or_fallback(
            llm, body.nl_text, body.available_columns
        )
    except ValueError as exc:
        # Bad-input path: helper couldn't produce a condition and didn't
        # fall back to the threshold template. Surface as a client error.
        log.warning("compile-trigger bad input: %s", exc)
        raise HTTPException(status_code=422, detail="invalid trigger description")
    except Exception as exc:  # noqa: BLE001
        # Everything else (TimeoutError, httpx errors, auth failures,
        # provider outages) is infrastructure, not user input. Surface as
        # 502 so the FE can show "AI service unavailable" instead of
        # misleading the user that their NL description was malformed.
        log.error("compile-trigger LLM infrastructure failure: %s", exc)
        raise HTTPException(status_code=502, detail="AI service unavailable")
    finally:
        # Phase 1.2 — emit usage record for the NL→JSON compile call.
        try:
            t_in = (
                int(getattr(llm, "input_tokens_used", 0) or 0)
                - _tokens_before_in
            )
            t_out = (
                int(getattr(llm, "output_tokens_used", 0) or 0)
                - _tokens_before_out
            )
            if t_in > 0 or t_out > 0:
                from ..config import get_settings
                from ..metrics.llm_usage import record_llm_usage

                _settings = get_settings()
                record_llm_usage(
                    source="trigger_compile",
                    provider="gemini",
                    model=getattr(
                        llm, "model", _settings.gemini_chat_model
                    ),
                    input_tokens=t_in,
                    output_tokens=t_out,
                    user_id=user.id,
                    # source_ref_id is None until the trigger is persisted
                    # against an automation; callers can later join by
                    # user_id + created_at window.
                    source_ref_id=None,
                )
        except Exception:  # noqa: BLE001
            pass


@router.post("/generate-sql")
async def generate_sql(
    body: GenerateSQLRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    llm = _resolve_llm(request)
    try:
        return await ai_sql_mod.generate_sql(llm, body.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Automation CRUD
# ---------------------------------------------------------------------------


@router.post("")
async def create_automation(
    body: CreateAutomationRequest,
    user: CurrentUser = Depends(get_current_user),
):
    _validate_sql_queries(body.sql_queries)
    try:
        return await asyncio.to_thread(_svc().create, body, user.id)
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_automations(
    user: CurrentUser = Depends(get_current_user),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int | None = Query(default=None, ge=0),
):
    # Back-compat: when neither limit nor offset is supplied, return the bare
    # list (existing FE shape). When either is supplied, return the paginated
    # envelope.
    if limit is None and offset is None:
        return await asyncio.to_thread(
            _svc().list_for_user, user.id, _is_admin(user)
        )
    eff_limit = limit if limit is not None else 50
    eff_offset = offset if offset is not None else 0
    items, total = await asyncio.to_thread(
        _svc().list_for_user_paged,
        user.id,
        _is_admin(user),
        limit=eff_limit,
        offset=eff_offset,
    )
    return {
        "items": items,
        "total": total,
        "limit": eff_limit,
        "offset": eff_offset,
    }


@router.get("/{automation_id}")
async def get_automation(
    automation_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(
            _svc().get, automation_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)


@router.put("/{automation_id}")
async def update_automation(
    automation_id: str,
    body: UpdateAutomationRequest,
    user: CurrentUser = Depends(get_current_user),
):
    if body.sql_queries is not None:
        _validate_sql_queries(body.sql_queries)
    try:
        return await asyncio.to_thread(
            _svc().update, automation_id, body, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError, AutomationError) as exc:
        raise _not_found_or_forbidden(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{automation_id}")
async def delete_automation(
    automation_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        await asyncio.to_thread(
            _svc().delete, automation_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)
    return {"status": "ok"}


@router.post("/{automation_id}/toggle")
async def toggle_automation(
    automation_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(
            _svc().toggle, automation_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)


@router.post("/{automation_id}/runs")
async def manual_run(
    automation_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    # Owner-or-admin scope enforced by a get() call first
    try:
        await asyncio.to_thread(
            _svc().get, automation_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)

    batch = await runner.run_due_automations(
        request.app, automation_id=automation_id
    )
    return {
        "status": "ok",
        "ran": [item.model_dump() for item in batch.ran],
    }


@router.get("/{automation_id}/runs")
async def list_runs(
    automation_id: str,
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        return await asyncio.to_thread(
            _svc().list_runs, automation_id, user.id, _is_admin(user), limit
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)


@router.get("/{automation_id}/runs/{run_id}")
async def get_run(
    automation_id: str,
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(
            _svc().get_run, automation_id, run_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)


# ---------------------------------------------------------------------------
# Trigger templates
# ---------------------------------------------------------------------------


@templates_router.get("")
async def list_templates(
    user: CurrentUser = Depends(get_current_user),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int | None = Query(default=None, ge=0),
):
    if limit is None and offset is None:
        return await asyncio.to_thread(
            _tpl_svc().list_for_user, user.id, _is_admin(user)
        )
    eff_limit = limit if limit is not None else 50
    eff_offset = offset if offset is not None else 0
    items, total = await asyncio.to_thread(
        _tpl_svc().list_for_user_paged,
        user.id,
        _is_admin(user),
        limit=eff_limit,
        offset=eff_offset,
    )
    return {
        "items": items,
        "total": total,
        "limit": eff_limit,
        "offset": eff_offset,
    }


@templates_router.post("")
async def create_template(
    body: CreateTriggerTemplateRequest,
    user: CurrentUser = Depends(get_current_user),
):
    return await asyncio.to_thread(
        _tpl_svc().create,
        name=body.name,
        description=body.description,
        conditions=body.conditions,
        owner_user_id=user.id,
    )


@templates_router.get("/{template_id}")
async def get_template(
    template_id: str, user: CurrentUser = Depends(get_current_user)
):
    try:
        return await asyncio.to_thread(
            _tpl_svc().get, template_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)


@templates_router.put("/{template_id}")
async def update_template(
    template_id: str,
    body: UpdateTriggerTemplateRequest,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return await asyncio.to_thread(
            _tpl_svc().update,
            template_id,
            name=body.name,
            description=body.description,
            conditions=body.conditions,
            user_id=user.id,
            is_admin=_is_admin(user),
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)


@templates_router.delete("/{template_id}")
async def delete_template(
    template_id: str, user: CurrentUser = Depends(get_current_user)
):
    try:
        await asyncio.to_thread(
            _tpl_svc().delete, template_id, user.id, _is_admin(user)
        )
    except (NotFoundError, ForbiddenError) as exc:
        raise _not_found_or_forbidden(exc)
    return {"status": "ok"}
