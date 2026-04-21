"""Unit tests for ``SqlExecutorStage`` against an on-disk tmp SQLite DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from insightxpert_api.pipeline.executor_stage import SqlExecutorStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.services.database_service import DatabaseService
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter
from insightxpert_api.storage.local import LocalStorage


def _seed(bundled: Path) -> None:
    con = sqlite3.connect(str(bundled / "demo.sqlite"))
    con.executescript(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);"
        "INSERT INTO users(id, name) VALUES (1, 'alice'), (2, 'bob');"
    )
    con.commit()
    con.close()


@pytest.mark.asyncio
async def test_executor_emits_rows(tmp_path):
    bundled = tmp_path / "Databases"
    bundled.mkdir()
    _seed(bundled)
    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(bundled), store=store)
    stage = SqlExecutorStage(db_svc=db_svc)

    emitter = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=emitter)
    ctx.state["db_id"] = "demo"
    ctx.state["sql"] = "SELECT COUNT(*) AS n FROM users"

    result = await stage.run(ctx, None)
    await emitter.close()

    assert result is not None
    assert result["rows"] == [[2]]

    frames = []
    async for f in emitter.stream():
        frames.append(f)
    joined = "".join(frames)
    assert ChunkType.SQL_EXECUTING.value in joined
    assert ChunkType.ROWS_RETURNED.value in joined


@pytest.mark.asyncio
async def test_executor_sets_error_on_failure(tmp_path):
    bundled = tmp_path / "Databases"
    bundled.mkdir()
    _seed(bundled)
    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(bundled), store=store)
    stage = SqlExecutorStage(db_svc=db_svc)

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["db_id"] = "demo"
    ctx.state["sql"] = "SELECT * FROM does_not_exist"

    result = await stage.run(ctx, None)
    assert result is None
    assert ctx.state["error"].startswith("sql_execution_failed")


@pytest.mark.asyncio
async def test_executor_is_noop_when_prior_error(tmp_path):
    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(tmp_path / "nope"), store=store)
    stage = SqlExecutorStage(db_svc=db_svc)

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["error"] = "upstream"
    ctx.state["db_id"] = "demo"
    ctx.state["sql"] = "SELECT 1"
    assert await stage.run(ctx, None) is None
