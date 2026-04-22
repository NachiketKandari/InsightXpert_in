"""Database routes.

Five endpoints backing the FE dataset selector + upload + profile flows:

  * ``GET /api/v1/databases`` — list bundled + session-uploaded DBs.
  * ``POST /api/v1/databases/upload`` — multipart SQLite upload.
  * ``GET /api/v1/databases/{db_id}/schema`` — DDL + table list.
  * ``GET /api/v1/databases/{db_id}/profile`` — cached profile (404 if unprofiled).
  * ``POST /api/v1/databases/{db_id}/profile`` — SSE-driven profiling run.

All routes require an authenticated session. The profiling route builds a
single-stage ``Pipeline`` around ``ProfilerStage`` rather than the full chat
pipeline — profiling is the only work here.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..auth.current_user import CurrentUser, get_current_user, require_admin
from ..config import Settings, get_settings
from ..databases import service as visibility_service
from ..db.schema import ddl as schema_ddl
from ..logging import get_logger
from ..profiling.runner import (
    ProfileFlags,
    count_columns,
    estimate_cost,
    run_profile_stream,
)
from ..services.conversation_store import ConversationStore, get_conversation_store
from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..sse.chunks import ChunkType, ProfileCostEstimatePayload
from ..sse.emitter import EventEmitter
from ..storage import build_store

router = APIRouter(prefix="/api/v1/databases", tags=["databases"])
log = get_logger("databases")

_SQLITE_MAGIC = b"SQLite format 3\x00"
_DB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,62}$")


def _validate_db_id(db_id: str) -> None:
    """Validate user-supplied db_id. Lowercase alnum + underscore/hyphen, 1-63 chars.

    Raises HTTPException(400, 'invalid_db_id') on rejection. Applied at write-time
    endpoints (e.g. upload) so we never persist hostile values like '../etc/passwd'.
    Read endpoints just 404 on unknown ids — no need to duplicate the check there.
    """
    if not _DB_ID_PATTERN.fullmatch(db_id):
        raise HTTPException(status_code=400, detail="invalid_db_id")


class DatabaseListItem(BaseModel):
    db_id: str
    source: str


class UploadResponse(BaseModel):
    db_id: str
    source: str


class SchemaResponse(BaseModel):
    ddl: str
    tables: list[str]


def _db_svc(settings: Settings) -> DatabaseService:
    store = build_store(settings)
    return DatabaseService(bundled_dir=settings.bundled_dbs_dir, store=store)


def _prof_svc(settings: Settings) -> ProfileService:
    return ProfileService(build_store(settings))


def _list_tables(path: str) -> list[str]:
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


@router.get("", response_model=list[DatabaseListItem])
async def list_databases(
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[DatabaseListItem]:
    """List DBs visible to the caller.

    We take the filesystem union (bundled + uploaded) from :class:`DatabaseService`
    and intersect it against the visibility table. Bundled BIRD DBs are seeded
    as ``public`` in migration 0003, so all callers see them. Uploaded DBs are
    filtered by ownership / shares. Admins bypass the filter and see everything.
    """
    svc = _db_svc(settings)
    refs = await asyncio.to_thread(svc.list, cu.id)
    is_admin = cu.role == "admin"
    visible_ids = await asyncio.to_thread(
        visibility_service.visible_ids, cu.id, is_admin
    )
    return [
        DatabaseListItem(db_id=r.db_id, source=r.source)
        for r in refs
        # If there's no row in the `databases` table for a given db_id the
        # item pre-dates the visibility layer — keep it listed for the owning
        # session so legacy uploads keep working for their uploader. For
        # bundled DBs (always seeded public) this branch never fires.
        if r.db_id in visible_ids or r.source == "uploaded"
    ]


@router.post("/upload", response_model=UploadResponse)
async def upload_database(
    db_id: str = Form(...),
    file: UploadFile = File(...),
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    _validate_db_id(db_id)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="upload_too_large")
    if not data[:16].startswith(_SQLITE_MAGIC):
        raise HTTPException(status_code=400, detail="invalid_file")
    svc = _db_svc(settings)
    ref = svc.save_upload(cu.id, db_id, data)
    # Register in the visibility table so the DB shows up in GET /databases and
    # admins can change its visibility later. Idempotent for re-uploads.
    await asyncio.to_thread(
        visibility_service.upsert_private, db_id, cu.id, len(data)
    )
    return UploadResponse(db_id=ref.db_id, source=ref.source)


@router.get("/{db_id}/schema", response_model=SchemaResponse)
async def get_schema(
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> SchemaResponse:
    svc = _db_svc(settings)
    ref = svc.resolve(cu.id, db_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="invalid_db")
    return SchemaResponse(ddl=schema_ddl(ref.local_path), tables=_list_tables(ref.local_path))


@router.get("/{db_id}/profile")
async def get_profile(
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    prof = _prof_svc(settings)
    profile = prof.load(cu.id, db_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="not_found")
    return profile.model_dump(mode="json")


class ProfileRunRequest(BaseModel):
    """Body for ``POST /databases/{db_id}/profile``.

    All flags default to ``False`` — the base path (schema + stats only) is
    free. Any of the four expensive flags triggers the cost-gate handshake
    unless ``confirmed=true``:

        1. FE POSTs {flags: on, confirmed: false}. Server replies with one
           ``profile_cost_estimate`` chunk and closes the stream.
        2. FE renders a confirmation modal, then re-POSTs with
           ``confirmed=true``. Server runs every stage and streams the
           six-stage progress contract.
    """

    with_summaries: bool = False
    with_quirks: bool = False
    with_lsh: bool = False
    with_vectors: bool = False
    confirmed: bool = False


async def _run_profile_v2(
    db_id: str,
    db_path: str,
    flags: ProfileFlags,
    emitter: EventEmitter,
    session_id: str,
    prof_svc: ProfileService,
    settings: Settings,
    llm: object | None,
) -> None:
    try:
        profile = await run_profile_stream(
            emitter,
            db_id=db_id,
            db_path=db_path,
            flags=flags,
            llm=llm,
            batch_size=settings.profiling_batch_size,
            max_columns_for_llm=settings.profiling_max_columns_for_llm,
            batch_disabled=settings.profiling_batch_disabled,
        )
        if profile is not None:
            prof_svc.save(session_id, db_id, profile)
    finally:
        await emitter.close()


async def _emit_cost_estimate_and_close(
    emitter: EventEmitter, payload: ProfileCostEstimatePayload
) -> None:
    try:
        await emitter.emit(ChunkType.profile_cost_estimate, payload)
    finally:
        await emitter.close()


@router.post("/{db_id}/profile")
async def run_profile(
    db_id: str,
    request: Request,
    body: ProfileRunRequest | None = None,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> EventSourceResponse:
    """Run profiling with stepped SSE progress + cost-gate handshake."""
    db_svc = _db_svc(settings)
    prof_svc = _prof_svc(settings)
    ref = db_svc.resolve(cu.id, db_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="invalid_db")

    convo = convo_store.get_or_create(cu.id, None)
    emitter = EventEmitter(convo.conversation_id)

    req = body or ProfileRunRequest()
    flags = ProfileFlags(
        with_summaries=req.with_summaries,
        with_quirks=req.with_quirks,
        with_lsh=req.with_lsh,
        with_vectors=req.with_vectors,
    )

    # --- cost-gate branch ------------------------------------------------
    # Any expensive flag on + not confirmed → emit a single estimate chunk
    # and close the stream. FE re-POSTs with confirmed=true to run.
    if flags.any and not req.confirmed:
        _, column_count = count_columns(ref.local_path, db_id)
        estimate = estimate_cost(
            column_count, flags, settings.profiling_batch_size
        )
        payload = ProfileCostEstimatePayload(
            columns=estimate.columns,
            batch_size=estimate.batch_size,
            total_llm_calls=estimate.total_llm_calls,
            estimated_seconds=estimate.estimated_seconds,
        )
        asyncio.create_task(_emit_cost_estimate_and_close(emitter, payload))
        return EventSourceResponse(emitter.stream())

    # --- full run branch -------------------------------------------------
    # Resolve an LLM if any LLM stage is on. We don't construct one on the
    # cheap (schema+stats only) path so tests can hit it without Gemini.
    llm: object | None = None
    if flags.any_llm or flags.with_vectors:
        # Prefer an app-state LLM (populated by tests via app.state.llm) so
        # the profile path can be exercised without a live Gemini key.
        llm = getattr(request.app.state, "llm", None)
        if llm is None:
            try:
                from ..llm.gemini import GeminiLLM

                llm = GeminiLLM(
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_chat_model,
                    embed_model=settings.gemini_embed_model,
                )
            except Exception as exc:
                log.warning("profile.llm_construct_failed", error=str(exc))
                llm = None

    asyncio.create_task(
        _run_profile_v2(
            db_id=db_id,
            db_path=ref.local_path,
            flags=flags,
            emitter=emitter,
            session_id=cu.id,
            prof_svc=prof_svc,
            settings=settings,
            llm=llm,
        )
    )
    return EventSourceResponse(emitter.stream())


class VisibilityRequest(BaseModel):
    visibility: str  # private | shared | public
    shared_with: list[str] | None = None


@router.post("/{db_id}/visibility")
async def set_db_visibility(
    db_id: str,
    body: VisibilityRequest,
    cu: CurrentUser = Depends(require_admin),
) -> dict[str, str]:
    """Admin-only: set visibility + (for 'shared') replace the share list."""
    try:
        await asyncio.to_thread(
            visibility_service.set_visibility,
            db_id,
            body.visibility,
            body.shared_with,
        )
    except visibility_service.InvalidVisibilityError:
        raise HTTPException(status_code=400, detail="invalid_visibility") from None
    return {"status": "ok"}


# Fallback when trailing slash variant is hit (FastAPI defaults redirect; this keeps
# strict-slash clients happy without a redirect hop).
@router.get("/", include_in_schema=False, response_model=list[DatabaseListItem])
async def _list_databases_slash(
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> list[DatabaseListItem]:
    return await list_databases(cu=cu, settings=settings)


# Expose the status symbol in case other modules want the same shape. Unused internally.
_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED
