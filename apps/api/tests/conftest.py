"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.config import Settings, get_settings
from insightxpert_api.main import create_app
from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType, SQLGeneratedPayload, StatusPayload


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Populate required env for every test."""
    monkeypatch.setenv("SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("APP_ENV", "local")
    # Force a per-test SQLite file. Without this, .env.local (loaded from the
    # api package root) leaks the dev DATABASE_URL into tests — including
    # Supabase Postgres, which tests must never touch. `fresh_db` and friends
    # may override this further; this is just the safe floor.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
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
def authed_client(fresh_db) -> Iterator[TestClient]:
    """A TestClient pre-authenticated as a regular user.

    Post-B1: the old anonymous gate is gone, so "authed" means a real user
    record + /login. Kept as a distinct fixture from ``user_client`` to avoid
    touching every legacy call site; it yields just the TestClient for
    backward compatibility.
    """
    from insightxpert_api.main import create_app
    from insightxpert_api.users import service as users_service
    from insightxpert_api.users.models import CreateUserInput

    invited = users_service.invite(CreateUserInput(email="authed@example.com", role="user"))
    c = TestClient(create_app())
    resp = c.post(
        "/api/v1/auth/login",
        json={"email": "authed@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    yield c


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

    def fake_factory(_s, _db, _pf, *, pipeline_mode: str = "linked"):
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


# --- auth fixtures --------------------------------------------------------


@pytest.fixture()
def user_client(fresh_db):
    """TestClient pre-authenticated as a regular user.

    Yields a tuple (client, user) so tests can assert on user.id when needed.
    """
    from fastapi.testclient import TestClient

    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    invited = service.invite(CreateUserInput(email="user@example.com", role="user"))
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    yield client, invited.user


@pytest.fixture()
def automations_env(monkeypatch):
    """Enable the automations feature flag for a test."""
    monkeypatch.setenv("AUTOMATIONS_ENABLED", "true")
    monkeypatch.setenv("AUTOMATIONS_SCHEDULER_MODE", "embedded")
    monkeypatch.setenv("AUTOMATIONS_SCHEDULER_TICK_SECONDS", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def automations_external_env(monkeypatch):
    """Enable automations with external scheduler mode + valid secret."""
    monkeypatch.setenv("AUTOMATIONS_ENABLED", "true")
    monkeypatch.setenv("AUTOMATIONS_SCHEDULER_MODE", "external")
    monkeypatch.setenv(
        "AUTOMATIONS_SCHEDULER_SECRET", "x" * 40
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def user_client_automations(fresh_db, automations_env):
    from fastapi.testclient import TestClient

    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    invited = service.invite(CreateUserInput(email="auto_user@example.com", role="user"))
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auto_user@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    yield client, invited.user


@pytest.fixture()
def admin_client_automations(fresh_db, automations_env):
    from fastapi.testclient import TestClient

    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    invited = service.invite(CreateUserInput(email="auto_admin@example.com", role="admin"))
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auto_admin@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    yield client, invited.user


@pytest.fixture()
def admin_client(fresh_db):
    from fastapi.testclient import TestClient

    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    invited = service.invite(CreateUserInput(email="admin@example.com", role="admin"))
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": invited.temp_password},
    )
    assert resp.status_code == 200
    yield client, invited.user
