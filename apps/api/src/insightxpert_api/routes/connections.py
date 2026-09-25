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
from ..connections.oracle_connector import TableDetails, is_system_schema
from ..connections.postgres_connector import PostgresConnector
from ..connections.types import (
    LibsqlConnection,
    MySQLConnection,
    OracleConnection,
    PostgresConnection,
)
from ..databases import repository as databases_repo
from ..logging import get_logger
from ..profiling import repository as profiles_repo

_log = get_logger("connections")


router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


class ConnectionRequest(BaseModel):
    db_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]{0,63}$")
    kind: str
    config: dict[str, Any]
    # Table-picker allowlist (oracle only in v1). None/empty = all tables.
    selected_tables: list[str] | None = None


def _build_typed_config(kind: str, raw: dict[str, Any]) -> Any:
    """Validate ``raw`` against the Pydantic model for ``kind``. Raises 400."""
    if kind == "postgres":
        try:
            return PostgresConnection(**raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid postgres config: {e}")
    if kind == "mysql":
        try:
            return MySQLConnection(**raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid mysql config: {e}")
    if kind == "oracle":
        try:
            return OracleConnection(**raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid oracle config: {e}")
    if kind == "libsql":
        try:
            return LibsqlConnection(**raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"invalid libsql config: {e}")
    raise HTTPException(status_code=400, detail=f"unsupported kind: {kind}")


def _oracle_table_details(cfg: OracleConnection) -> list[TableDetails]:
    """Run Oracle discovery (tables + columns + row counts). Raises 400/501."""
    from ..connections.oracle_connector import OracleConnector

    try:
        conn = OracleConnector(cfg)
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    try:
        try:
            return conn.discovery_details()
        except ValueError as e:
            # Config-level refusal (e.g. system schema).
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            _log.warning("connection test failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail="connection failed: unable to reach host or invalid credentials",
            )
    finally:
        conn.dispose()


def _details_payload(details: list[TableDetails]) -> dict[str, Any]:
    return {
        d.name: {
            "row_count": d.row_count,
            "column_count": d.column_count,
            "unsupported_columns": d.unsupported_columns,
        }
        for d in details
    }


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
    if req.kind == "mysql":
        from ..connections.mysql_connector import MySQLConnector

        conn = MySQLConnector(cfg)
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
    if req.kind == "oracle":
        cfg = _build_typed_config(req.kind, req.config)
        assert isinstance(cfg, OracleConnection)
        details = _oracle_table_details(cfg)
        tables = [d.name for d in details]
        return {"ok": True, "tables": tables, "details": _details_payload(details)}
    raise HTTPException(status_code=400, detail=f"unsupported kind: {req.kind}")


def _validate_oracle_selection(
    cfg: OracleConnection, selected: list[str] | None
) -> OracleConnection:
    """Validate the picker's table selection against live discovery.

    * Every selected table must exist in the introspected schema.
    * No selected table may contain Phase-1-unsupported column types.
    * System schemas are refused outright.

    Returns a copy of ``cfg`` with ``selected_tables`` normalized
    (None = all tables). Raises 400 otherwise.
    """
    from ..connections.oracle_connector import OracleConnector

    if is_system_schema(cfg.effective_schema()):
        raise HTTPException(
            status_code=400,
            detail=f"refusing to connect to system schema {cfg.effective_schema()!r}",
        )
    if not selected:
        return cfg.model_copy(update={"selected_tables": None})
    try:
        conn = OracleConnector(cfg)
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e))
    try:
        try:
            details = conn.discovery_details()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            _log.warning("connection validation failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail="connection failed: unable to reach host or invalid credentials",
            )
        by_name = {d.name.upper(): d for d in details}
        unknown = [t for t in selected if t.upper() not in by_name]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown tables for this schema: {sorted(unknown)}",
            )
        blocked = {
            d.name: d.unsupported_columns
            for t in selected
            if (d := by_name[t.upper()]).unsupported_columns
        }
        if blocked:
            flat = "; ".join(
                f"{name} ({', '.join(cols)})" for name, cols in sorted(blocked.items())
            )
            raise HTTPException(
                status_code=400,
                detail=f"tables with unsupported column types (BLOB/RAW are phase-1): {flat}",
            )
    finally:
        conn.dispose()
    return cfg.model_copy(update={"selected_tables": list(selected)})


@router.post("", status_code=201)
async def create_connection(
    req: ConnectionRequest,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    # Validate config first (raises 400 if invalid).
    cfg = _build_typed_config(req.kind, req.config)

    if req.selected_tables and req.kind != "oracle":
        raise HTTPException(
            status_code=400,
            detail="selected_tables is only supported for oracle in v1",
        )

    # Reject if db_id is taken by another owner.
    existing = databases_repo.get(req.db_id)
    if existing and existing.get("owner_user_id") not in (None, cu.id):
        raise HTTPException(status_code=409, detail="db_id taken")

    config_json = json.dumps(req.config)
    if req.kind == "oracle":
        # Re-validate the selection against live discovery (subset check +
        # BLOB/RAW rejection). Unlike other kinds, oracle save DOES open a
        # connection — the table picker allowlist must be verified before we
        # persist it, otherwise a forged allowlist could bypass the Phase-1
        # binary-type rejection.
        assert isinstance(cfg, OracleConnection)
        cfg = _validate_oracle_selection(cfg, req.selected_tables)
        config_json = cfg.model_dump_json(by_alias=True)

    encrypted = encrypt(config_json)
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
