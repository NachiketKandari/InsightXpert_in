"""Unit tests for ``SqlRefinerStage`` with a stubbed LLM + tmp SQLite DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from insightxpert_api.pipeline.refiner_stage import SqlRefinerStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.services.database_service import DatabaseService
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter
from insightxpert_api.storage.local import LocalStorage

REFINE_PROMPT = str(
    Path(__file__).resolve().parents[2]
    / "src/insightxpert_api/vendored/pipeline_core/prompts/refine_sql.j2"
)


def _seed(bundled: Path) -> None:
    con = sqlite3.connect(str(bundled / "demo.sqlite"))
    con.executescript("CREATE TABLE users (id INTEGER); INSERT INTO users VALUES (1),(2),(3);")
    con.commit()
    con.close()


@pytest.mark.asyncio
async def test_refiner_is_noop_without_error(tmp_path):
    llm = MagicMock()
    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(tmp_path / "nope"), store=store)
    stage = SqlRefinerStage(
        llm=llm, max_iters=2, db_svc=db_svc, prompt_path=REFINE_PROMPT
    )
    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["sql"] = "SELECT 1"
    result = await stage.run(ctx, None)
    assert result == "SELECT 1"


@pytest.mark.asyncio
async def test_refiner_fixes_sql(tmp_path):
    bundled = tmp_path / "Databases"
    bundled.mkdir()
    _seed(bundled)

    llm = MagicMock()

    async def _gen(prompt: str, **_):
        assert "Execution Feedback" in prompt
        return "```sql\nSELECT COUNT(*) FROM users\n```"

    llm.async_generate = _gen

    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(bundled), store=store)
    stage = SqlRefinerStage(
        llm=llm, max_iters=2, db_svc=db_svc, prompt_path=REFINE_PROMPT
    )
    emitter = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=emitter)
    ctx.state["db_id"] = "demo"
    ctx.state["question"] = "how many users?"
    ctx.state["schema_text"] = 'Table: "users"'
    ctx.state["sql"] = "SELECT * FROM nope"
    ctx.state["error"] = "sql_execution_failed: no such table: nope"

    result = await stage.run(ctx, None)
    await emitter.close()

    assert result == "SELECT COUNT(*) FROM users"
    assert "error" not in ctx.state
    assert ctx.state["rows"]["rows"] == [[3]]

    frames = []
    async for f in emitter.stream():
        frames.append(f)
    joined = "".join(frames)
    assert '"iteration": 1' in joined
    assert ChunkType.ROWS_RETURNED.value in joined
