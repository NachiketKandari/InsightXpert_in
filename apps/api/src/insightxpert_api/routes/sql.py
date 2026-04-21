"""SQL execute route.

Powers the forked FE's SQL drawer. Read-only; write attempts are rejected by
``DatabaseConnector.FORBIDDEN_SQL_RE`` before they ever touch SQLite.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.dependencies import require_session
from ..auth.session import SessionClaims
from ..config import Settings, get_settings
from ..db.connector import DatabaseConnector, ForbiddenSQLError, SQLTimeoutError
from ..services.database_service import DatabaseService
from ..storage import build_store

router = APIRouter(prefix="/api/v1/sql", tags=["sql"])


class SqlExecuteRequest(BaseModel):
    db_id: str = Field(min_length=1, max_length=128)
    sql: str = Field(min_length=1)


class SqlExecuteResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: int


@router.post("/execute", response_model=SqlExecuteResponse)
async def execute_sql(
    body: SqlExecuteRequest,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
) -> SqlExecuteResponse:
    store = build_store(settings)
    svc = DatabaseService(bundled_dir=settings.bundled_dbs_dir, store=store)
    ref = svc.resolve(claims.session_id, body.db_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="invalid_db")

    connector = DatabaseConnector(
        ref.local_path,
        row_limit=settings.sql_row_limit,
        timeout_s=settings.sql_timeout_seconds,
    )
    try:
        result = connector.execute(body.sql)
    except ForbiddenSQLError as e:
        raise HTTPException(status_code=400, detail="sql_forbidden_write") from e
    except SQLTimeoutError as e:
        raise HTTPException(status_code=408, detail="sql_timeout") from e
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=400, detail="sql_syntax") from e

    return SqlExecuteResponse(
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        execution_time_ms=result.execution_time_ms,
    )
