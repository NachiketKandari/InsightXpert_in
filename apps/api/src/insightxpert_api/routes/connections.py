"""External DB connection management — test, save, list, delete.

Backs the BYO-DB feature. Connection configs are validated by Pydantic, the
"test" endpoint actually opens a connection (and lists tables) before we
agree to persist, and the secret is encrypted with Fernet before it touches
the registry.

Mounted under ``/api/v1/connections`` by ``main.create_app``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..auth import CurrentUser, get_current_user
from ..connections.encryption import encrypt
from ..connections.postgres_connector import PostgresConnector
from ..connections.types import LibsqlConnection, PostgresConnection
from ..databases import repository as databases_repo
from ..logging import get_logger
from ..profiling import repository as profiles_repo

_log = get_logger("connections")


router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


class ConnectionRequest(BaseModel):
    db_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]{0,63}$")
    kind: str
    config: dict[str, Any]


def _build_typed_config(kind: str, raw: dict[str, Any]) -> Any:
    """Validate ``raw`` against the Pydantic model for ``kind``. Raises 400."""
    if kind == "postgres":
        try:
            return PostgresConnection(**raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid postgres config: {e}")
    if kind == "libsql":
        try:
            return LibsqlConnection(**raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid libsql config: {e}")
    raise HTTPException(status_code=400, detail=f"unsupported kind: {kind}")


@router.post("/test")
async def test_connection(
    req: ConnectionRequest,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    cfg = _build_typed_config(req.kind, req.config)
    if req.kind == "postgres":
        conn = PostgresConnector(cfg)
        try:
            tables = conn.list_tables()
        except Exception as e:
            _log.warning("connection test failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail="connection failed: unable to reach host or invalid credentials",
            )
        finally:
            conn.dispose()
        return {"ok": True, "tables": tables}
    if req.kind == "libsql":
        # Reserved by the Turso cutover plan — surface a clear 501 rather than
        # silently accepting and failing later.
        raise HTTPException(status_code=501, detail="libsql test not yet implemented")
    raise HTTPException(status_code=400, detail=f"unsupported kind: {req.kind}")


@router.post("", status_code=201)
async def create_connection(
    req: ConnectionRequest,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    # Validate config first (raises 400 if invalid).
    _build_typed_config(req.kind, req.config)

    # Reject if db_id is taken by another owner.
    existing = databases_repo.get(req.db_id)
    if existing and existing.get("owner_user_id") not in (None, cu.id):
        raise HTTPException(status_code=409, detail="db_id taken")

    encrypted = encrypt(json.dumps(req.config))
    databases_repo.upsert_private(
        db_id=req.db_id,
        owner_user_id=cu.id,
        size_bytes=0,
        kind=req.kind,
        connection_config_encrypted=encrypted,
    )
    return {"db_id": req.db_id}


@router.get("")
async def list_connections(
    response: Response,
    cu: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "private, max-age=10"
    rows = await asyncio.to_thread(databases_repo.list_owned, cu.id)
    # NEVER return connection_config_encrypted or its decrypted contents.
    # Bundled / uploaded sqlite_file rows are surfaced via /api/v1/databases.
    return [
        {
            "db_id": r["db_id"],
            "kind": r["kind"],
            "created_at": r["created_at"],
        }
        for r in rows
        if r.get("kind") not in ("sqlite_file", None)
    ]


@router.delete("/{db_id}", status_code=204)
async def delete_connection(
    db_id: str,
    cu: CurrentUser = Depends(get_current_user),
) -> None:
    row = databases_repo.get(db_id)
    if not row:
        raise HTTPException(status_code=404)
    if row["owner_user_id"] != cu.id:
        raise HTTPException(status_code=403)
    profiles_repo.delete_overrides_for_db(db_id)
    profiles_repo.delete_for_db(db_id)
    databases_repo.delete(db_id)
    return None
