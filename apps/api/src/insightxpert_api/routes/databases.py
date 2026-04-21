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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import require_session
from ..auth.session import SessionClaims
from ..config import Settings, get_settings
from ..db.schema import ddl as schema_ddl
from ..logging import get_logger
from ..pipeline.pipeline import Pipeline
from ..pipeline.profiler_stage import ProfilerStage
from ..pipeline.stage import PipelineContext
from ..services.conversation_store import ConversationStore, get_conversation_store
from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..sse.chunks import ChunkType, ErrorPayload
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
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> list[DatabaseListItem]:
    svc = _db_svc(settings)
    return [DatabaseListItem(db_id=r.db_id, source=r.source) for r in svc.list(claims.session_id)]


@router.post("/upload", response_model=UploadResponse)
async def upload_database(
    db_id: str = Form(...),
    file: UploadFile = File(...),
    claims: SessionClaims = Depends(require_session),
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
    ref = svc.save_upload(claims.session_id, db_id, data)
    return UploadResponse(db_id=ref.db_id, source=ref.source)


@router.get("/{db_id}/schema", response_model=SchemaResponse)
async def get_schema(
    db_id: str,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> SchemaResponse:
    svc = _db_svc(settings)
    ref = svc.resolve(claims.session_id, db_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="invalid_db")
    return SchemaResponse(ddl=schema_ddl(ref.local_path), tables=_list_tables(ref.local_path))


@router.get("/{db_id}/profile")
async def get_profile(
    db_id: str,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    prof = _prof_svc(settings)
    profile = prof.load(claims.session_id, db_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="not_found")
    return profile.model_dump(mode="json")


async def _run_profile_pipeline(
    pipeline: Pipeline, ctx: PipelineContext
) -> None:
    emitter = ctx.emitter
    try:
        await pipeline.run_scalar(ctx, None)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "profile.pipeline_failed",
            session_id=ctx.session_id,
            db_id=ctx.state.get("db_id"),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        if emitter is not None:
            await emitter.emit(
                ChunkType.ERROR,
                ErrorPayload(code="profile_failed", detail=str(exc)),
            )
    finally:
        if emitter is not None:
            await emitter.close()


@router.post("/{db_id}/profile")
async def run_profile(
    db_id: str,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> EventSourceResponse:
    """Kick off profiling as a single-stage Pipeline, stream SSE progress."""
    db_svc = _db_svc(settings)
    prof_svc = _prof_svc(settings)
    if db_svc.resolve(claims.session_id, db_id) is None:
        raise HTTPException(status_code=404, detail="invalid_db")

    convo = convo_store.get_or_create(claims.session_id, None)
    emitter = EventEmitter(convo.conversation_id)
    pipeline = Pipeline([ProfilerStage(db_svc=db_svc, prof_svc=prof_svc)])

    ctx = PipelineContext(
        session_id=claims.session_id,
        conversation_id=convo.conversation_id,
        emitter=emitter,
    )
    ctx.state["db_id"] = db_id

    asyncio.create_task(_run_profile_pipeline(pipeline, ctx))
    return EventSourceResponse(emitter.stream())


# Fallback when trailing slash variant is hit (FastAPI defaults redirect; this keeps
# strict-slash clients happy without a redirect hop).
@router.get("/", include_in_schema=False, response_model=list[DatabaseListItem])
async def _list_databases_slash(
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> list[DatabaseListItem]:
    return await list_databases(claims=claims, settings=settings)


# Expose the status symbol in case other modules want the same shape. Unused internally.
_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED
