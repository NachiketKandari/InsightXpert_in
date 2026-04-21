"""Integration tests for ``ProfilerStage``.

Two tests:
  * A fast unit-ish test that builds a tiny SQLite on disk and runs the stage
    end-to-end without any network/LLM dependency. This guards the
    profile→cache→SSE emission path in CI.
  * An opt-in slow test against the bundled ``california_schools.sqlite``.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

from insightxpert_api.pipeline.profiler_stage import ProfilerStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.services.database_service import DatabaseService
from insightxpert_api.services.profile_service import ProfileService
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter
from insightxpert_api.storage.local import LocalStorage


def _make_tiny_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        INSERT INTO users(id, name) VALUES (1, 'alice'), (2, 'bob'), (3, 'carol');
        """
    )
    con.commit()
    con.close()


def test_profiler_stage_runs_and_caches(tmp_path):
    bundled = tmp_path / "Databases"
    bundled.mkdir()
    _make_tiny_db(bundled / "demo.sqlite")

    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(bundled), store=store)
    prof_svc = ProfileService(store)
    stage = ProfilerStage(db_svc=db_svc, prof_svc=prof_svc)

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["db_id"] = "demo"

    profile = asyncio.run(stage.run(ctx, None))
    assert profile.db_id == "demo"
    assert len(profile.tables) == 1
    assert profile.tables[0].name == "users"
    assert prof_svc.exists("s", "demo")

    # Second run must hit the cache (identical result, same db_id).
    profile2 = asyncio.run(stage.run(ctx, None))
    assert profile2.db_id == profile.db_id


def test_profiler_stage_emits_profile_loaded(tmp_path):
    bundled = tmp_path / "Databases"
    bundled.mkdir()
    _make_tiny_db(bundled / "demo.sqlite")

    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(bundled), store=store)
    prof_svc = ProfileService(store)
    stage = ProfilerStage(db_svc=db_svc, prof_svc=prof_svc)

    async def _run() -> list:
        emitter = EventEmitter(conversation_id="c")
        ctx = PipelineContext(
            session_id="s", conversation_id="c", emitter=emitter
        )
        ctx.state["db_id"] = "demo"
        await stage.run(ctx, None)
        await emitter.close()
        events = []
        async for frame in emitter.stream():
            events.append(frame)
        return events

    frames = asyncio.run(_run())
    joined = "".join(frames)
    assert ChunkType.PROFILE_LOADED.value in joined
    assert '"from_cache": false' in joined


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY_REAL"),
    reason="needs a real Gemini key (set GEMINI_API_KEY_REAL to run)",
)
def test_profiler_stage_on_bundled_db(tmp_path):
    """Opt-in: profile the real bundled ``california_schools.sqlite``.

    Run locally with:
        GEMINI_API_KEY_REAL=... uv run pytest tests/integration/test_profiler_stage.py -v -k bundled
    """
    bundled = Path(__file__).resolve().parents[2] / "Databases"
    if not (bundled / "california_schools.sqlite").exists():
        pytest.skip("california_schools.sqlite not bundled")

    store = LocalStorage(str(tmp_path / "store"))
    db_svc = DatabaseService(bundled_dir=str(bundled), store=store)
    prof_svc = ProfileService(store)
    stage = ProfilerStage(db_svc=db_svc, prof_svc=prof_svc)

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["db_id"] = "california_schools"
    profile = asyncio.run(stage.run(ctx, None))
    assert profile.db_id == "california_schools"
    assert len(profile.tables) > 0
