import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.gemini  # skipped in CI without API key
def test_seed_script_writes_sample_questions(fresh_db):
    """End-to-end: seed-bundled-profiles.py populates sample_questions for a bundled DB.

    Marked @pytest.mark.gemini because it spends a real LLM call. Skipped in CI.
    """
    db_id = "california_schools"
    env = os.environ.copy()
    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    subprocess.check_call(
        [sys.executable, "scripts/seed-bundled-profiles.py", "--db-id", db_id],
        cwd=api_dir,
        env=env,
    )
    from insightxpert_api.sample_questions import repository
    sq = repository.get_sample_questions(db_id)
    assert sq is not None
    assert sq.status.value in {"ok", "fallback"}
