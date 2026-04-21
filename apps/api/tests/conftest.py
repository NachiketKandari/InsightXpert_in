"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.auth.session import SessionSigner
from insightxpert_api.config import Settings, get_settings
from insightxpert_api.main import create_app
from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType, SQLGeneratedPayload, StatusPayload


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate required env for every test."""
    monkeypatch.setenv("GATE_PASSWORD", "test-pw")
    monkeypatch.setenv("SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def authed_client(client: TestClient, settings: Settings) -> TestClient:
    """A TestClient with a valid signed session cookie pre-set."""
    token = SessionSigner(settings).issue()
    client.cookies.set(settings.session_cookie_name, token)
    return client


class _FakeGen:
    name = "sql_generator"

    async def run(self, ctx: PipelineContext, _: Any) -> str:
        sql = "SELECT 1 AS n"
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=sql))
        ctx.state["sql"] = sql
        return sql


class _FakeExec:
    name = "sql_executor"

    async def run(self, ctx: PipelineContext, _: Any) -> None:
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.STATUS, StatusPayload(message="executed"))
        ctx.state["rows"] = [[1]]
        ctx.state["answer"] = "The answer is 1."
        return None


@pytest.fixture
def patched_pipeline(monkeypatch):
    """Swap default_pipeline for a 2-stage fake so pipeline-driven routes are testable
    without Gemini. Shared across chat SSE, /chat/poll, /chat/answer tests.
    """

    def fake_factory(_s, _db, _pf):
        return Pipeline([_FakeGen(), _FakeExec()])

    with patch("insightxpert_api.routes.chat.default_pipeline", side_effect=fake_factory):
        yield


# ---------------------------------------------------------------------------
# fresh_db — isolated SQLite database with migrations applied
# ---------------------------------------------------------------------------

from pathlib import Path

from alembic import command
from alembic.config import Config


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Provision a brand-new SQLite file with migrations applied.

    Returns the DATABASE_URL string; also sets it in the process env and
    clears the settings + engine cache so the app sees it.
    """
    db = tmp_path / "test.db"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)

    from insightxpert_api.config import get_settings
    from insightxpert_api.db.engine import reset_engine_cache
    get_settings.cache_clear()
    reset_engine_cache()

    api_dir = Path(__file__).resolve().parents[1]  # apps/api
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    yield url

    reset_engine_cache()
    get_settings.cache_clear()
