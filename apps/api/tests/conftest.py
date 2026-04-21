"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.auth.session import SessionSigner
from insightxpert_api.config import Settings, get_settings
from insightxpert_api.main import create_app


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
