import pytest
from fastapi.testclient import TestClient

from insightxpert_api.config import get_settings
from insightxpert_api.main import create_app


def test_health_returns_ok(monkeypatch):
    monkeypatch.setenv("GATE_PASSWORD", "x")
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "z")
    get_settings.cache_clear()

    import insightxpert_api.routes.health as health_mod
    monkeypatch.setattr(health_mod, "_state", health_mod._HealthState(db_reachable=True, db_latency_ms=5.0))

    client = TestClient(create_app())
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["db"]["reachable"] is True


def _drive_checker(monkeypatch, probes, max_ticks):
    """Run the background checker against a scripted probe sequence.

    ``probes`` is the list of (ok, latency_ms) results returned in order —
    first element is the initial probe, the rest feed the loop ticks. The
    patched sleep returns immediately and raises CancelledError after
    ``max_ticks`` calls, which stops the loop like app shutdown would.
    """
    import asyncio

    import insightxpert_api.routes.health as health_mod

    results = iter(probes)

    async def fake_probe():
        return next(results, (True, 1.0))

    calls = {"n": 0}

    async def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] > max_ticks:
            raise asyncio.CancelledError()

    monkeypatch.setattr(health_mod, "_probe", fake_probe)
    monkeypatch.setattr(health_mod.asyncio, "sleep", fake_sleep)
    return health_mod


async def test_health_checker_debounces_single_failed_ping(monkeypatch):
    """A single slow/failed DB ping must not flip /health to 503.

    One-off Supabase pooler hiccups used to flap the endpoint to 503, which
    painted "Backend unavailable" banners in every connected browser even
    though the app was healthy.
    """
    health_mod = _drive_checker(
        monkeypatch,
        probes=[(True, 5.0), (False, 0.0), (True, 7.0)],
        max_ticks=2,
    )

    await health_mod.run_health_checker()

    assert health_mod._state.db_reachable is True
    assert health_mod._state.db_latency_ms == 7.0


async def test_health_checker_flags_persistent_failures(monkeypatch):
    """Consecutive failed pings do report the DB as unreachable (→ 503)."""
    health_mod = _drive_checker(
        monkeypatch,
        probes=[(True, 5.0), (False, 0.0), (False, 0.0)],
        max_ticks=2,
    )

    await health_mod.run_health_checker()

    assert health_mod._state.db_reachable is False


async def test_health_checker_recovers_immediately(monkeypatch):
    """One successful ping restores reachable=True right away."""
    health_mod = _drive_checker(
        monkeypatch,
        probes=[(True, 5.0), (False, 0.0), (False, 0.0), (True, 4.0)],
        max_ticks=3,
    )

    await health_mod.run_health_checker()

    assert health_mod._state.db_reachable is True
    assert health_mod._state.db_latency_ms == 4.0

