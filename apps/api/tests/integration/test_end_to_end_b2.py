"""Phase B2 end-to-end smoke test: real Gemini, both agent modes.

Gated on ``GEMINI_API_KEY_REAL`` — the autouse ``GEMINI_API_KEY=test-key`` env
from ``conftest`` keeps the rest of the suite offline. This test exercises the
orchestrator_loop path (basic + agentic) against a bundled BIRD SQLite sample.

Run locally:

    cd apps/api
    GEMINI_API_KEY_REAL=$(grep '^GEMINI_API_KEY=' .env.local | cut -d= -f2-) \
      uv run pytest tests/integration/test_end_to_end_b2.py -v --timeout=90

Both subtests should pass; combined wall clock should stay <60 s on a healthy
link (agentic turn dominates; if it exceeds the budget repeatedly, tune the
question or raise the per-test timeout — but NEVER hide a real failure).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.config import get_settings
from insightxpert_api.main import create_app

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "Databases"
_DB_ID = "toxicology"

# Tier-3 chunks that must appear in BOTH modes, in this relative order.
_REQUIRED_ORDERED = ["sql_generated", "sql_executing", "rows_returned", "answer_generated"]

# Tier-4 (agentic-only) transparency chunks — at least one must fire in agentic.
_AGENTIC_ANY = {"orchestrator_plan", "agent_trace", "enrichment_trace", "insight"}

requires_real_gemini = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY_REAL"),
    reason="needs a real Gemini API key (GEMINI_API_KEY_REAL)",
)


@pytest.fixture
def real_client(monkeypatch: pytest.MonkeyPatch, fresh_db) -> TestClient:
    """TestClient wired to the real Gemini key + bundled DB dir."""
    from insightxpert_api.users import service as users_service
    from insightxpert_api.users.models import CreateUserInput

    real_key = os.environ["GEMINI_API_KEY_REAL"]
    monkeypatch.setenv("GEMINI_API_KEY", real_key)
    monkeypatch.setenv("BUNDLED_DBS_DIR", str(BUNDLED_DIR))
    monkeypatch.setenv("SESSION_SECRET", "s" * 32)
    get_settings.cache_clear()

    invited = users_service.invite(CreateUserInput(email="e2e-b2@example.com", role="user"))
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "e2e-b2@example.com", "password": invited.temp_password},
    )
    assert r.status_code == 200, r.text
    return client


def _ordered_subseq_present(types: list[str], required: list[str]) -> bool:
    """Return True iff every item in ``required`` appears in ``types`` in order."""
    it = iter(types)
    return all(any(t == r for t in it) for r in required)


@pytest.mark.slow
@requires_real_gemini
def test_e2e_b2_basic_mode_against_toxicology(real_client: TestClient):
    """basic mode: pipeline-only path must emit the Tier-3 chunk sequence."""
    assert (BUNDLED_DIR / f"{_DB_ID}.sqlite").exists(), (
        "bundled DB missing; run apps/api/scripts/fetch-bundled-dbs.sh"
    )

    t0 = time.monotonic()
    r = real_client.post(
        "/api/v1/chat/poll",
        json={
            "db_id": _DB_ID,
            "message": "How many molecules are in the database?",
            "agent_mode": "basic",
        },
    )
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text

    body = r.json()
    chunks = body["chunks"]
    types = [c["type"] for c in chunks]

    # All four Tier-3 chunks present, and in the required relative order.
    for required in _REQUIRED_ORDERED:
        assert required in types, f"missing {required!r} in basic mode: types={types}"
    assert _ordered_subseq_present(types, _REQUIRED_ORDERED), (
        f"basic mode chunks out of order: {types}"
    )

    # Answer text non-empty.
    answer_chunks = [c for c in chunks if c["type"] == "answer_generated"]
    assert answer_chunks, "no answer_generated chunk"
    answer_text = answer_chunks[-1].get("data", {}).get("text") or ""
    assert answer_text.strip(), f"empty answer text: {answer_chunks[-1]!r}"

    print(f"\n[e2e-b2] basic mode wall-clock: {elapsed:.2f}s  chunks={types}")


@pytest.mark.slow
@requires_real_gemini
def test_e2e_b2_agentic_mode_against_toxicology(real_client: TestClient):
    """agentic mode: Tier-3 sequence PLUS at least one Tier-4 transparency chunk."""
    assert (BUNDLED_DIR / f"{_DB_ID}.sqlite").exists(), (
        "bundled DB missing; run apps/api/scripts/fetch-bundled-dbs.sh"
    )

    t0 = time.monotonic()
    r = real_client.post(
        "/api/v1/chat/poll",
        json={
            "db_id": _DB_ID,
            "message": "How many molecules are carcinogenic versus non-carcinogenic?",
            "agent_mode": "agentic",
        },
    )
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text

    body = r.json()
    chunks = body["chunks"]
    types = [c["type"] for c in chunks]

    # Tier-3 sequence still present (agentic wraps the same analyst path).
    for required in _REQUIRED_ORDERED:
        assert required in types, f"missing {required!r} in agentic mode: types={types}"
    assert _ordered_subseq_present(types, _REQUIRED_ORDERED), (
        f"agentic mode chunks out of order: {types}"
    )

    # At least one Tier-4 orchestration-transparency chunk fires.
    tier4_seen = _AGENTIC_ANY & set(types)
    assert tier4_seen, (
        f"no Tier-4 orchestration chunk in agentic mode; expected one of "
        f"{sorted(_AGENTIC_ANY)}; got types={types}"
    )

    # Answer text non-empty.
    answer_chunks = [c for c in chunks if c["type"] == "answer_generated"]
    assert answer_chunks, "no answer_generated chunk"
    answer_text = answer_chunks[-1].get("data", {}).get("text") or ""
    assert answer_text.strip(), f"empty answer text: {answer_chunks[-1]!r}"

    print(
        f"\n[e2e-b2] agentic mode wall-clock: {elapsed:.2f}s  "
        f"tier4_seen={sorted(tier4_seen)}  chunks={types}"
    )
