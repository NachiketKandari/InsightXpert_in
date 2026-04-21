from fastapi.testclient import TestClient

from insightxpert_api.config import get_settings
from insightxpert_api.main import create_app


def test_health_returns_ok(monkeypatch):
    monkeypatch.setenv("GATE_PASSWORD", "x")
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "z")
    get_settings.cache_clear()
    client = TestClient(create_app())
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
