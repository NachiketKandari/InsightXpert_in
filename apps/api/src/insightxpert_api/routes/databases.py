"""Database routes.

Endpoints backing the FE dataset selector + upload + profile flows:

  * ``GET /api/v1/databases`` — list bundled + session-uploaded DBs.
  * ``POST /api/v1/databases/upload`` — multipart SQLite upload.
  * ``POST /api/v1/databases/upload-csv`` — CSV/Excel→SQLite conversion upload.
  * ``POST /api/v1/databases/upload-preview`` — preview CSV/Excel before upload.
  * ``GET /api/v1/databases/{db_id}/schema`` — DDL + table list.
  * ``GET /api/v1/databases/{db_id}/profile`` — cached profile (404 if unprofiled).
  * ``POST /api/v1/databases/{db_id}/profile`` — SSE-driven profiling run.

All routes require an authenticated session. The profiling route builds a
single-stage ``Pipeline`` around ``ProfilerStage`` rather than the full chat
pipeline — profiling is the only work here.
"""

from __future__ import annotations

import asyncio
import functools
import io
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Coroutine

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..auth.current_user import CurrentUser, get_current_user, require_admin
from ..config import Settings, get_settings
from ..databases import repository as databases_repo
from ..databases import service as visibility_service
from ..db.dialects import get_adapter
from ..db.schema import ddl as schema_ddl
from ..logging import get_logger
from ..profiling import repository as profiles_repo
from ..profiling.cache import get_process_profile_cache
from ..profiling.runner import (
    ProfileFlags,
    count_columns,
    estimate_cost,
    run_profile_stream,
)
from ..services.conversation_store import ConversationStore, get_conversation_store
from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..jobs.sample_questions_job import run_sample_questions_job
from ..sample_questions import repository as sq_repo
from ..sse.chunks import ChunkType, ProfileCostEstimatePayload, ProfileDonePayload
from ..sse.emitter import EventEmitter
from ..storage import build_store

router = APIRouter(prefix="/api/v1/databases", tags=["databases"])
log = get_logger("databases")

# Strong refs for fire-and-forget tasks — prevents CPython GC from
# collecting them mid-flight (asyncio docs warn about this).
_background_tasks: set[asyncio.Task[Any]] = set()


def _spawn_background_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task

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
    has_profile: bool = False
    table_count: int | None = None
    column_count: int | None = None
    row_count: int | None = None


class UploadResponse(BaseModel):
    db_id: str
    source: str
    profile_required: bool = False


class PreviewColumn(BaseModel):
    name: str
    inferred_type: str
    sample_values: list[str]
    null_count: int
    distinct_count: int


class SheetPreview(BaseModel):
    sheet_name: str
    columns: list[PreviewColumn]
    preview_rows: list[dict[str, str]]
    row_count: int


class UploadPreviewResponse(BaseModel):
    columns: list[PreviewColumn]
    preview_rows: list[dict[str, str]]
    row_count: int
    encoding: str | None = None
    sheet_name: str | None = None
    sheet_names: list[str] | None = None
    sheets: list[SheetPreview] | None = None
    file_size_bytes: int


class SchemaResponse(BaseModel):
    ddl: str
    tables: list[str]


def _db_svc(settings: Settings) -> DatabaseService:
    store = build_store(settings)
    return DatabaseService(bundled_dir=settings.bundled_dbs_dir, store=store)


def _prof_svc(settings: Settings) -> ProfileService:
    # ProfileService ignores the store parameter — it only uses the
    # process-level ProfileCache.  Avoid constructing an unnecessary
    # ObjectStore (which creates a GCS client in prod) on every call.
    return ProfileService()


def _list_tables(ref: Any) -> list[str]:
    """List table names in the database described by ``ref``.

    For SQLite: queries sqlite_master directly.
    For Postgres: intentional stub — table listing via information_schema lands in Task 10.
    """
    if ref.dialect == "sqlite":
        adapter = get_adapter(ref.dialect)
        con = adapter.open_readonly(ref)
        try:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            con.close()
        return [r[0] for r in rows]

    # Intentional stub: Postgres table listing via information_schema lands in Task 10.
    raise NotImplementedError(
        f"Table listing for dialect {ref.dialect!r} is not yet implemented "
        "(Postgres table listing lands in Task 10)"
    )


@router.get("", response_model=list[DatabaseListItem])
async def list_databases(
    response: Response,
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
    is_admin = cu.role == "admin"
    response.headers["Cache-Control"] = "private, max-age=10"
    # Run all three independent data fetches in parallel — they have no
    # dependency on each other. Wall time drops from sum-of-three to
    # max-of-three.
    refs, visible_ids, summaries = await asyncio.gather(
        asyncio.to_thread(svc.list, cu.id),
        asyncio.to_thread(visibility_service.visible_ids, cu.id, is_admin),
        asyncio.to_thread(profiles_repo.list_summaries),
    )
    out: list[DatabaseListItem] = []
    for r in refs:
        # If there's no row in the `databases` table for a given db_id the
        # item pre-dates the visibility layer — keep it listed for the owning
        # session so legacy uploads keep working for their uploader. For
        # bundled DBs (always seeded public) this branch never fires.
        if r.db_id not in visible_ids and r.source != "uploaded":
            continue
        s = summaries.get(r.db_id)
        out.append(
            DatabaseListItem(
                db_id=r.db_id,
                source=r.source,
                has_profile=s is not None,
                table_count=s["table_count"] if s else None,
                column_count=s["column_count"] if s else None,
                row_count=s["row_count"] if s else None,
            )
        )
    return out


@router.post("/upload", response_model=UploadResponse)
async def upload_database(
    db_id: str = Form(...),
    file: UploadFile = File(...),
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    _validate_db_id(db_id)

    # Block upload collisions BEFORE reading the body: a bundled public row
    # (owner=NULL) or a row owned by a different user must 409 — otherwise
    # user B uploading db_id="toxicology" would silently overwrite user A's
    # ownership/visibility via upsert_private (MF-PR-4).
    existing = await asyncio.to_thread(databases_repo.get, db_id)
    if existing is not None:
        owner = existing.get("owner_user_id")
        if owner is None or owner != cu.id:
            raise HTTPException(
                status_code=409,
                detail=f"db_id '{db_id}' is already registered to another owner or is bundled-public; pick a different db_id",
            )

    # Stream the upload in chunks, tracking size as we go, so a 5 GB file
    # can't OOM us before the 413 fires (MF-PR-1). Peek the first 16 bytes
    # of the first chunk for the SQLite magic (MF-PR-2) so we reject
    # non-sqlite uploads before reading further.
    max_bytes = settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    first_chunk = True
    while True:
        chunk = await file.read(1 << 20)  # 1 MiB
        if not chunk:
            break
        if first_chunk:
            if not chunk[:16].startswith(_SQLITE_MAGIC):
                raise HTTPException(status_code=400, detail="invalid_file")
            first_chunk = False
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="upload_too_large")
        chunks.append(chunk)
    if first_chunk:
        # Empty body — never got a first chunk; still fail-closed.
        raise HTTPException(status_code=400, detail="invalid_file")
    data = b"".join(chunks)

    svc = _db_svc(settings)
    ref = svc.save_upload(cu.id, db_id, data)
    # Register in the visibility table so the DB shows up in GET /databases and
    # admins can change its visibility later. Idempotent for re-uploads by the
    # SAME user (cross-owner collision was blocked above).
    await asyncio.to_thread(
        visibility_service.upsert_private, db_id, cu.id, len(data)
    )
    return UploadResponse(db_id=ref.db_id, source=ref.source)


def _file_to_dataframe(raw_bytes: bytes, filename: str) -> tuple[dict[str, "pd.DataFrame"], dict]:
    """Parse CSV or Excel file into DataFrames with metadata.

    Returns (dataframes_dict, metadata) where dataframes_dict maps sheet name
    to DataFrame. For CSV files the dict has a single key ``"data"``. For XLSX
    files every sheet becomes its own entry. Metadata includes encoding, sheet
    info, and per-sheet row counts.

    Does NOT sanitise column names — that happens in ``_dataframe_to_sqlite``
    so preview can show original names.
    """
    import pandas as pd  # always available (in pyproject.toml dependencies)

    ext = Path(filename).suffix.lower()
    meta: dict = {}

    if ext in (".xlsx", ".xls"):
        if ext == ".xls":
            raise HTTPException(
                status_code=400,
                detail="Legacy .xls format is not supported. Please save as .xlsx or .csv and try again.",
            )
        try:
            xls = pd.ExcelFile(io.BytesIO(raw_bytes))
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="Excel support requires openpyxl. Please install it.",
            )
        except Exception as exc:
            msg = str(exc)
            if "password" in msg.lower() or "encrypted" in msg.lower():
                raise HTTPException(status_code=400, detail="This Excel file is password-protected. Please remove the password and try again.")
            if "corrupt" in msg.lower() or "not a valid" in msg.lower():
                raise HTTPException(status_code=400, detail="This file appears to be corrupted or unsupported. Please check the file and try again.")
            raise HTTPException(status_code=400, detail=f"Could not read Excel file: {msg}") from exc

        sheet_names: list = xls.sheet_names
        meta["sheet_names"] = sheet_names
        meta["sheet_name"] = sheet_names[0]

        # Read all sheets — sheet_name=None returns dict[str, DataFrame].
        try:
            dfs = pd.read_excel(xls, sheet_name=None, dtype=object)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read Excel file: {exc}") from exc
        finally:
            xls.close()

        meta["original_rows"] = sum(len(d) for d in dfs.values())
        if len(sheet_names) > 1:
            log.info(
                "multi_sheet_excel",
                filename=filename,
                sheets=sheet_names,
                per_sheet_rows={k: len(v) for k, v in dfs.items()},
            )
        return dfs, meta

    # CSV path — encoding detection via fallback chain.
    encodings = ["utf-8", "latin-1", "cp1252"]
    last_exc: Exception | None = None
    for enc in encodings:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), dtype=object, encoding=enc)
            meta["encoding"] = enc
            break
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue
        except pd.errors.EmptyDataError:
            raise HTTPException(status_code=400, detail="File has no data rows.")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"malformed_csv: {exc}") from exc
    else:
        raise HTTPException(
            status_code=400,
            detail="Could not detect file encoding. Try saving as UTF-8 CSV or .xlsx.",
        ) from last_exc

    if df.empty and len(df.columns) == 0:
        raise HTTPException(status_code=400, detail="File has no data rows.")

    meta["original_rows"] = len(df)
    return {"data": df}, meta


def _infer_column_types(df: "pd.DataFrame") -> dict[str, str]:
    """Infer SQLite types for each column in a DataFrame.

    Strategy (same as legacy _csv_to_sqlite):
      * Boolean-looking columns → INTEGER
      * Numeric columns → INTEGER (if exact) or REAL
      * Datetime-looking columns (>50% parse) → DATETIME
      * Everything else → TEXT
    """
    import pandas as pd

    col_types: dict[str, str] = {}
    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            col_types[col] = "TEXT"
            continue

        bool_vals = {"true", "false", "1", "0"}
        str_series = series.astype(str).str.lower()
        if set(str_series.unique()).issubset(bool_vals):
            col_types[col] = "INTEGER"
            continue

        numeric = pd.to_numeric(series, errors="coerce")
        non_null = numeric.dropna()
        if len(non_null) == len(series):
            if (non_null == non_null.astype("int64")).all():
                col_types[col] = "INTEGER"
            else:
                col_types[col] = "REAL"
            continue

        dt = pd.to_datetime(series, errors="coerce", utc=False)
        if dt.notna().sum() / len(series) > 0.5:
            col_types[col] = "DATETIME"
            continue

        col_types[col] = "TEXT"
    return col_types


def _dataframe_to_sqlite(df: "pd.DataFrame", db_id: str) -> bytes:
    """Write a DataFrame to an in-memory SQLite, return serialised bytes.

    Sanitises column names, deduplicates, infers types, creates table, and
    inserts rows in batches. The table name is derived from ``db_id``.
    """
    import pandas as pd

    # Sanitise column names: strip whitespace, replace non-alphanumeric with _.
    rename_map = {}
    for col in df.columns:
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", str(col).strip())
        if not safe or safe[0].isdigit():
            safe = f"col_{safe}"
        rename_map[col] = safe
    df = df.rename(columns=rename_map)

    # Deduplicate column names in case sanitisation produced collisions.
    seen: dict[str, int] = {}
    final_cols: list[str] = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            final_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            final_cols.append(col)
    df.columns = pd.Index(final_cols)

    col_types = _infer_column_types(df)

    # Build the in-memory SQLite.
    con = sqlite3.connect(":memory:")
    table_name = re.sub(r"[^a-z0-9_]", "_", db_id.lower())
    cols_ddl = ", ".join(f'"{col}" {col_types[col]}' for col in df.columns)
    con.execute(f'CREATE TABLE "{table_name}" ({cols_ddl})')

    def _coerce(val: object, col_type: str) -> object:
        if val is None or (isinstance(val, float) and val != val):
            return None
        if col_type == "INTEGER":
            try:
                return int(float(str(val)))
            except (ValueError, TypeError):
                return None
        if col_type == "REAL":
            try:
                return float(str(val))
            except (ValueError, TypeError):
                return None
        return str(val)

    placeholders = ", ".join("?" * len(df.columns))
    col_list = ", ".join(f'"{c}"' for c in df.columns)
    batch: list[tuple[object, ...]] = []
    for row in df.itertuples(index=False, name=None):
        batch.append(tuple(_coerce(v, col_types[c]) for v, c in zip(row, df.columns)))
        if len(batch) >= 500:
            con.executemany(
                f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
                batch,
            )
            batch.clear()
    if batch:
        con.executemany(
            f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
            batch,
        )
    con.commit()
    blob = con.serialize()
    con.close()
    return bytes(blob)


def _sheet_name_to_table(sheet_name: str) -> str:
    """Sanitize an Excel sheet name to a valid SQLite table name.

    Lowercase, replace non-alphanumeric with underscore, prefix digit-leading
    names with ``t_``. Empty names become ``unnamed``.
    """
    safe = re.sub(r"[^a-z0-9_]", "_", sheet_name.lower().strip())
    if not safe:
        safe = "unnamed"
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe


def _dataframes_to_sqlite(dfs: dict[str, "pd.DataFrame"]) -> bytes:
    """Write multiple DataFrames to a single in-memory SQLite database.

    Each key in ``dfs`` becomes a table (after sanitisation via
    ``_sheet_name_to_table``). Returns the serialised SQLite bytes.

    Deduplicates table names when two sheet names sanitise to the same value
    by appending ``_2``, ``_3``, etc.
    """
    import pandas as pd

    con = sqlite3.connect(":memory:")
    used_names: dict[str, int] = {}

    for sheet_name, df in dfs.items():
        # --- Sanitise column names (same as _dataframe_to_sqlite) ---
        rename_map = {}
        for col in df.columns:
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", str(col).strip())
            if not safe or safe[0].isdigit():
                safe = f"col_{safe}"
            rename_map[col] = safe
        df = df.rename(columns=rename_map)

        seen: dict[str, int] = {}
        final_cols: list[str] = []
        for col in df.columns:
            if col in seen:
                seen[col] += 1
                final_cols.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                final_cols.append(col)
        df.columns = pd.Index(final_cols)

        col_types = _infer_column_types(df)

        # --- Sanitise sheet name → table name ---
        base = _sheet_name_to_table(sheet_name)
        if base in used_names:
            used_names[base] += 1
            table_name = f"{base}_{used_names[base]}"
        else:
            used_names[base] = 1
            table_name = base

        cols_ddl = ", ".join(f'"{col}" {col_types[col]}' for col in df.columns)
        con.execute(f'CREATE TABLE "{table_name}" ({cols_ddl})')

        def _coerce(val: object, col_type: str) -> object:
            if val is None or (isinstance(val, float) and val != val):
                return None
            if col_type == "INTEGER":
                try:
                    return int(float(str(val)))
                except (ValueError, TypeError):
                    return None
            if col_type == "REAL":
                try:
                    return float(str(val))
                except (ValueError, TypeError):
                    return None
            return str(val)

        placeholders = ", ".join("?" * len(df.columns))
        col_list = ", ".join(f'"{c}"' for c in df.columns)
        batch: list[tuple[object, ...]] = []
        for row in df.itertuples(index=False, name=None):
            batch.append(tuple(_coerce(v, col_types[c]) for v, c in zip(row, df.columns)))
            if len(batch) >= 500:
                con.executemany(
                    f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
                    batch,
                )
                batch.clear()
        if batch:
            con.executemany(
                f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
                batch,
            )

    con.commit()
    blob = con.serialize()
    con.close()
    return bytes(blob)


@router.post("/upload-csv", response_model=UploadResponse)
async def upload_csv(
    db_id: str = Form(...),
    file: UploadFile = File(...),
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Convert an uploaded CSV or Excel file to SQLite and register it.

    Supports ``.csv``, ``.xlsx``, and ``.xls``. Mirrors ``upload_database``
    defences (MF-PR-1/2/4):
      * Ownership collision check BEFORE reading the body.
      * Chunked read with running size check → 413 before OOM.
      * Empty body → 400.
      * Malformed CSV/Excel → 400.
      * db_id validation (path-traversal guard).

    Multi-sheet Excel files import every sheet as a separate table within the
    same SQLite database. CSV files produce a single table named ``"data"``.
    """
    _validate_db_id(db_id)

    # Validate file extension early.
    filename = file.filename or "upload.csv"
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload .csv, .xlsx, or .xls.",
        )

    # MF-PR-4: collision check before reading body.
    existing = await asyncio.to_thread(databases_repo.get, db_id)
    if existing is not None:
        owner = existing.get("owner_user_id")
        if owner is None or owner != cu.id:
            raise HTTPException(
                status_code=409,
                detail=f"db_id '{db_id}' is already registered to another owner or is bundled-public; pick a different db_id",
            )

    # MF-PR-1: chunked read with size cap.
    max_bytes = settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    first_chunk = True
    while True:
        chunk = await file.read(1 << 20)  # 1 MiB
        if not chunk:
            break
        first_chunk = False
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="upload_too_large")
        chunks.append(chunk)

    # MF-PR-2: empty body.
    if first_chunk:
        raise HTTPException(status_code=400, detail="invalid_file")

    raw_bytes = b"".join(chunks)

    # Parse file → dict[str, DataFrame] (blocking CPU work; run in thread pool).
    dfs, _meta = await asyncio.to_thread(_file_to_dataframe, raw_bytes, filename)

    # Convert DataFrames → multi-table SQLite.
    sqlite_bytes = await asyncio.to_thread(_dataframes_to_sqlite, dfs)

    svc = _db_svc(settings)
    ref = svc.save_upload(cu.id, db_id, sqlite_bytes)
    await asyncio.to_thread(
        visibility_service.upsert_private, db_id, cu.id, len(sqlite_bytes)
    )
    return UploadResponse(db_id=ref.db_id, source=ref.source, profile_required=True)


@router.post("/upload-preview", response_model=UploadPreviewResponse)
async def upload_preview(
    file: UploadFile = File(...),
    sheet: str | None = None,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> UploadPreviewResponse:
    """Preview a CSV or Excel file before uploading.

    Returns column metadata, inferred types, sample values, row count,
    and sheet information. Read-only — nothing is persisted.

    For multi-sheet Excel files, ``sheet`` selects which sheet to preview
    (defaults to the first sheet). The response includes a ``sheets`` field
    with per-sheet metadata for all sheets.
    """
    import pandas as pd

    filename = file.filename or "upload.csv"
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload .csv, .xlsx, or .xls.",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    first_chunk = True
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        first_chunk = False
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="upload_too_large")
        chunks.append(chunk)

    if first_chunk:
        raise HTTPException(status_code=400, detail="invalid_file")

    raw_bytes = b"".join(chunks)

    dfs, meta = await asyncio.to_thread(_file_to_dataframe, raw_bytes, filename)

    # Choose which sheet to show in the main preview.
    sheet_names = meta.get("sheet_names", list(dfs.keys()))
    active_sheet = sheet if sheet and sheet in dfs else sheet_names[0]

    # Build per-sheet previews.
    sheets: list[SheetPreview] = []
    total_row_count = 0
    for sname, sdf in dfs.items():
        s_col_types = _infer_column_types(sdf)
        s_columns: list[PreviewColumn] = []
        for col in sdf.columns:
            series = sdf[col]
            non_null = series.dropna()
            nn_vals = non_null.astype(str).tolist()
            sample = nn_vals[:3] + nn_vals[-2:] if len(nn_vals) > 5 else nn_vals[:5]
            s_columns.append(
                PreviewColumn(
                    name=str(col),
                    inferred_type=s_col_types.get(col, "TEXT"),
                    sample_values=sample,
                    null_count=int(series.isna().sum()),
                    distinct_count=int(series.nunique()),
                )
            )
        s_rows: list[dict[str, str]] = (
            sdf.head(5).fillna("").astype(str).to_dict(orient="records")
        )
        sheets.append(
            SheetPreview(
                sheet_name=sname,
                columns=s_columns,
                preview_rows=s_rows,
                row_count=len(sdf),
            )
        )
        total_row_count += len(sdf)

    active_df = dfs[active_sheet]
    active_types = _infer_column_types(active_df)

    columns: list[PreviewColumn] = []
    for col in active_df.columns:
        series = active_df[col]
        non_null = series.dropna()
        nn_vals = non_null.astype(str).tolist()
        sample = nn_vals[:3] + nn_vals[-2:] if len(nn_vals) > 5 else nn_vals[:5]
        columns.append(
            PreviewColumn(
                name=str(col),
                inferred_type=active_types.get(col, "TEXT"),
                sample_values=sample,
                null_count=int(series.isna().sum()),
                distinct_count=int(series.nunique()),
            )
        )

    preview_rows: list[dict[str, str]] = (
        active_df.head(5).fillna("").astype(str).to_dict(orient="records")
    )

    return UploadPreviewResponse(
        columns=columns,
        preview_rows=preview_rows,
        row_count=total_row_count,
        encoding=meta.get("encoding"),
        sheet_name=active_sheet,
        sheet_names=[s.sheet_name for s in sheets],
        sheets=sheets,
        file_size_bytes=len(raw_bytes),
    )


@router.get("/{db_id}/schema", response_model=SchemaResponse)
async def get_schema(
    db_id: str,
    response: Response,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> SchemaResponse:
    response.headers["Cache-Control"] = "private, max-age=10"
    svc = _db_svc(settings)
    ref = await asyncio.to_thread(svc.resolve, cu.id, db_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="invalid_db")
    ddl, tables = await asyncio.gather(
        asyncio.to_thread(schema_ddl, ref),
        asyncio.to_thread(_list_tables, ref),
    )
    return SchemaResponse(ddl=ddl, tables=tables)


@router.get("/{db_id}/profile")
async def get_profile(
    db_id: str,
    response: Response,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, max-age=10"
    prof = _prof_svc(settings)
    user_id = cu.id
    profile, sq = await asyncio.gather(
        asyncio.to_thread(prof.load, user_id, db_id),
        asyncio.to_thread(sq_repo.get_sample_questions, db_id),
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="not_found")
    out = profile.model_dump(mode="json")
    out["sample_questions"] = sq.model_dump(mode="json") if sq else None
    return out


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
    user_hints: str = ""


async def _run_profile_v2(
    db_id: str,
    db_path: str | None,
    flags: ProfileFlags,
    emitter: EventEmitter,
    session_id: str,
    prof_svc: ProfileService,
    settings: Settings,
    llm: object | None,
    user_id: str | None = None,
    user_hints: str = "",
    app: object | None = None,
    ref: object | None = None,
) -> None:
    try:
        run_start = time.monotonic()
        profile = await run_profile_stream(
            emitter,
            db_id=db_id,
            db_path=db_path or "",
            flags=flags,
            llm=llm,
            batch_size=settings.profiling_batch_size,
            max_columns_for_llm=settings.profiling_max_columns_for_llm,
            batch_disabled=settings.profiling_batch_disabled,
            indices_dir=settings.indices_dir,
            user_id=user_id,
            provider=settings.llm_provider,
            model=llm.model if llm and hasattr(llm, "model") else settings.gemini_chat_model,
            user_hints=user_hints,
            ref=ref,
        )
        if profile is not None:
            prof_svc.save(session_id, db_id, profile)
            # Emit profile_done AFTER save so the frontend doesn't race a GET
            # before the row is committed (PostgreSQL over the network).
            total_duration_ms = int((time.monotonic() - run_start) * 1000)
            await emitter.emit(
                ChunkType.profile_done,
                ProfileDonePayload(
                    db_id=db_id,
                    table_count=len(profile.tables),
                    column_count=sum(len(t.columns) for t in profile.tables),
                    summaries_populated=sum(
                        1 for t in profile.tables for c in t.columns if c.short_summary
                    ),
                    total_duration_ms=total_duration_ms,
                ),
            )
            # Persist join graph from disk to DB so the schema linker can load it.
            if settings.indices_dir:
                jg_path = Path(settings.indices_dir) / db_id / "join_graph.json"
                if jg_path.exists():
                    prof_svc.save_join_graph(
                        session_id, db_id, jg_path.read_text()
                    )
            # kick off sample-questions generation asynchronously
            _spawn_background_task(
                run_sample_questions_job(
                    db_id=db_id, llm=llm, model_name=llm.model if llm and hasattr(llm, "model") else settings.gemini_chat_model,
                    emitter=emitter, session_id=session_id,
                )
            )
            # Push a notification so the user knows profiling completed, even if
            # they left the database detail page and the SSE stream closed.
            if app is not None and user_id is not None:
                _spawn_background_task(
                    _push_profile_notification(
                        app=app,
                        user_id=user_id,
                        db_id=db_id,
                        table_count=len(profile.tables),
                        column_count=sum(len(t.columns) for t in profile.tables),
                    )
                )
    except Exception as exc:
        log.warning("profile.run_failed", db_id=db_id, error=str(exc))
        if app is not None and user_id is not None:
            _spawn_background_task(
                _push_profile_notification(
                    app=app,
                    user_id=user_id,
                    db_id=db_id,
                    table_count=0,
                    column_count=0,
                    error=str(exc),
                )
            )
    finally:
        await emitter.close()


async def _push_profile_notification(
    app: object,
    user_id: str,
    db_id: str,
    table_count: int,
    column_count: int,
    error: str = "",
) -> None:
    from ..automations.notifications import create as notif_create
    from ..automations.notifications import dispatch as notif_dispatch

    if error:
        notif = await asyncio.to_thread(
            notif_create,
            user_id,
            title="Profiling failed",
            message=f"Profiling for database failed: {error}",
            severity="error",
        )
    else:
        notif = await asyncio.to_thread(
            notif_create,
            user_id,
            title="Profiling complete",
            message=f"Database profiling complete: {table_count} tables, {column_count} columns analyzed.",
            severity="success",
        )
    try:
        await notif_dispatch(app, user_id, notif)
    except Exception as exc:
        log.warning("profile.notification_dispatch_failed", error=str(exc))


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
    from ..routes.chat import _chat_model

    db_svc = _db_svc(settings)
    prof_svc = _prof_svc(settings)
    ref = db_svc.resolve(cu.id, db_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="invalid_db")

    # Ownership gate (MF-PR-3). BEFORE any LLM spend — including the cost-gate
    # branch, so a non-owner can't even learn the column count of a private DB.
    # Admin + owner + public-bundled + shared-with-user all pass; everyone else
    # 403s. Uploads (no `databases` row) fall through because svc.resolve only
    # returns the ref when the user can see it via _list_uploaded.
    is_admin = cu.role == "admin"
    db_row = await asyncio.to_thread(databases_repo.get, db_id)
    if db_row is not None and not is_admin:
        owner = db_row.get("owner_user_id")
        visibility = db_row.get("visibility")
        is_owner = owner == cu.id
        is_public = visibility == "public"
        visible = await asyncio.to_thread(
            visibility_service.visible_ids, cu.id, False
        )
        is_shared = db_id in visible
        if not (is_owner or is_public or is_shared):
            raise HTTPException(status_code=403, detail="forbidden")

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
        _, column_count = count_columns(ref)
        estimate = estimate_cost(
            column_count, flags, settings.profiling_batch_size,
            provider=settings.llm_provider,
            model=_chat_model(settings),
        )
        payload = ProfileCostEstimatePayload(
            columns=estimate.columns,
            batch_size=estimate.batch_size,
            total_llm_calls=estimate.total_llm_calls,
            estimated_seconds=estimate.estimated_seconds,
            provider=estimate.provider,
            model=estimate.model,
        )
        asyncio.create_task(_emit_cost_estimate_and_close(emitter, payload))
        return EventSourceResponse(emitter.stream())

    # Phase 1.4 — per-user daily cap on LLM-driven profile runs. Only
    # enforced when an LLM stage is on; the cheap schema+stats path is
    # unmetered. Admins are exempt.
    if (flags.any_llm or flags.with_vectors) and not is_admin:
        from sqlalchemy import func, select

        from ..db.engine import get_engine
        from ..metrics.table import query_metrics

        window_start = int(time.time()) - 86_400

        def _count_recent_profile_runs() -> int:
            engine = get_engine()
            with engine.begin() as conn:
                row = conn.execute(
                    select(func.count())
                    .select_from(query_metrics)
                    .where(query_metrics.c.user_id == cu.id)
                    .where(query_metrics.c.source == "profile")
                    .where(query_metrics.c.created_at > window_start)
                ).scalar()
                return int(row or 0)

        recent = await asyncio.to_thread(_count_recent_profile_runs)
        if recent >= settings.profile_max_per_user_per_day:
            reset_epoch = window_start + 86_400
            raise HTTPException(
                status_code=429,
                detail=(
                    f"profile_quota_exceeded: {recent}/"
                    f"{settings.profile_max_per_user_per_day} profile runs in "
                    f"the last 24h. Resets at epoch {reset_epoch}."
                ),
            )

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
                from ..llm import create_chat_llm

                llm = create_chat_llm(settings)
            except Exception as exc:
                log.warning("profile.llm_construct_failed", error=str(exc))
                llm = None

    _spawn_background_task(
        _run_profile_v2(
            db_id=db_id,
            db_path=ref.local_path,
            flags=flags,
            emitter=emitter,
            session_id=cu.id,
            prof_svc=prof_svc,
            settings=settings,
            llm=llm,
            user_id=cu.id,
            user_hints=req.user_hints if req else "",
            app=request.app,
            ref=ref,
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
    get_process_profile_cache().invalidate(db_id, "base")
    return {"status": "ok"}


@router.post("/{db_id}/sample-questions/regenerate", status_code=202)
async def regenerate_sample_questions(
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _validate_db_id(db_id)
    prof = _prof_svc(settings)
    if prof.load(cu.id, db_id) is None:
        raise HTTPException(status_code=404, detail="profile_not_found")
    # fire-and-forget; idempotent inside the job
    from ..llm import create_chat_llm
    from ..routes.chat import _chat_model
    llm = create_chat_llm(settings) if (
        (settings.llm_provider == "deepseek" and settings.deepseek_api_key)
        or settings.gemini_api_key
    ) else None
    _spawn_background_task(
        run_sample_questions_job(
            db_id=db_id, llm=llm, model_name=_chat_model(settings),
            emitter=None, session_id=cu.id,
        )
    )
    existing = sq_repo.get_sample_questions(db_id)
    get_process_profile_cache().invalidate(db_id, "base")
    return {"status": existing.status.value if existing else "pending"}


@router.post("/{db_id}/sample-questions/ensure", status_code=200)
async def ensure_sample_questions(
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Idempotently ensure sample questions exist for a database.

    Safe to call on every DB-select — only triggers work when needed:
    - ok / fallback → return as-is (no-op)
    - pending → return as-is (generation already in flight)
    - null / failed → spawn background generation
    - no profile → 404

    This lets the FE prefetch questions when the user selects a DB rather
    than waiting until they open the sample-questions modal.
    """
    _validate_db_id(db_id)
    prof = _prof_svc(settings)
    if prof.load(cu.id, db_id) is None:
        raise HTTPException(status_code=404, detail="profile_not_found")

    existing = sq_repo.get_sample_questions(db_id)

    if existing is not None and existing.status in ("ok", "fallback"):
        return {"status": existing.status.value, "message": "Questions already exist"}

    if existing is not None and existing.status == "pending":
        return {"status": "pending", "message": "Generation already in progress"}

    # Null or failed — spawn background generation
    from ..llm import create_chat_llm
    from ..routes.chat import _chat_model
    llm = create_chat_llm(settings) if (
        (settings.llm_provider == "deepseek" and settings.deepseek_api_key)
        or settings.gemini_api_key
    ) else None
    _spawn_background_task(
        run_sample_questions_job(
            db_id=db_id, llm=llm, model_name=_chat_model(settings),
            emitter=None, session_id=cu.id,
        )
    )
    get_process_profile_cache().invalidate(db_id, "base")
    return {"status": "pending", "message": "Generation started"}


@router.get("/{db_id}/sample-questions/status")
async def get_sample_questions_status(
    response: Response,
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the current sample-question generation status + progress.

    Used by the FE to poll while a background generation is in flight, so the
    welcome-screen chips / progress bar can update without an active SSE stream.
    """
    response.headers["Cache-Control"] = "private, max-age=2"
    _validate_db_id(db_id)
    prof = _prof_svc(settings)
    if await asyncio.to_thread(prof.load, cu.id, db_id) is None:
        raise HTTPException(status_code=404, detail="profile_not_found")

    sq = await asyncio.to_thread(sq_repo.get_sample_questions, db_id)
    if sq is None:
        return {"status": "not_found", "generated_at": None, "progress": None}

    progress: dict[str, int] | None = None
    if sq.status == "pending":
        done = sum(
            1 for cat in sq.categories
            if cat.questions and cat.questions != ["…", "…", "…"]
        )
        progress = {"current": done, "total": len(sq.categories)}

    return {
        "status": sq.status.value,
        "generated_at": sq.generated_at.isoformat() if sq.generated_at else None,
        "model": sq.model,
        "progress": progress,
        "error": sq.error,
    }


class ProfileHintsRequest(BaseModel):
    hints: str


@router.put("/{db_id}/profile-hints")
async def set_profile_hints(
    db_id: str,
    body: ProfileHintsRequest,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Store pre-profiling domain hints for this database.

    These hints are threaded into the LLM prompts during profiling
    to improve column descriptions and quirk detection.
    """
    prof_svc = _prof_svc(settings)
    prof_svc.set_user_hints(cu.id, db_id, body.hints)
    get_process_profile_cache().invalidate(db_id, "base")
    return {"status": "ok"}


@router.get("/{db_id}/profile-hints")
async def get_profile_hints(
    response: Response,
    db_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, str | None]:
    """Get stored pre-profiling domain hints for this database."""
    response.headers["Cache-Control"] = "private, max-age=30"
    prof_svc = _prof_svc(settings)
    hints = await asyncio.to_thread(prof_svc.get_user_hints, "", db_id)
    return {"hints": hints}


class ColumnProfileUpdateRequest(BaseModel):
    field_path: str  # e.g. "short_summary", "long_summary", "quirks.semantic_hint", "quirks.aliases"
    value: object    # new value (JSON-encodable)


@router.patch("/{db_id}/profile/columns/{table_name}/{column_name}")
async def update_column_profile(
    db_id: str,
    table_name: str,
    column_name: str,
    body: ColumnProfileUpdateRequest,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Update a single field of a column profile.

    Supported field paths: ``short_summary``, ``long_summary``,
    ``quirks.semantic_hint``, ``quirks.aliases``, ``quirks.enum_labels``.
    Overrides are stored separately and applied on every profile read.
    """
    import json as _json

    prof_svc = _prof_svc(settings)
    value_json = _json.dumps(body.value)
    prof_svc.save_override(
        edited_by=cu.id,
        db_id=db_id,
        table_name=table_name,
        column_name=column_name,
        field_path=body.field_path,
        value_json=value_json,
    )
    return {"status": "ok"}


@router.delete("/{db_id}/profile/columns/{table_name}/{column_name}/overrides/{field_path}")
async def delete_column_override(
    db_id: str,
    table_name: str,
    column_name: str,
    field_path: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Revert a column profile field to its generated value."""
    prof_svc = _prof_svc(settings)
    count = prof_svc.delete_override(db_id, table_name, column_name, field_path)
    if not count:
        raise HTTPException(status_code=404, detail="override_not_found")
    return {"status": "ok"}


@router.get("/{db_id}/profile/overrides")
async def get_profile_overrides(
    response: Response,
    db_id: str,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    """Return all field overrides for a database profile."""
    response.headers["Cache-Control"] = "private, max-age=30"
    prof_svc = _prof_svc(settings)
    return await asyncio.to_thread(prof_svc.get_overrides, db_id)


@router.delete("/{db_id}/profile", status_code=204)
async def delete_profile(
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete all profiled data (profile row + overrides) for a database.

    Gated to the database owner and admins only.
    """
    db_row = await asyncio.to_thread(databases_repo.get, db_id)
    if db_row is None:
        raise HTTPException(status_code=404, detail="invalid_db")

    if cu.role != "admin" and db_row.get("owner_user_id") != cu.id:
        raise HTTPException(status_code=403, detail="forbidden")

    prof_svc = _prof_svc(settings)
    deleted = await asyncio.to_thread(prof_svc.delete_profile, db_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="no_profile")


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
