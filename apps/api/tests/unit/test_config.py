from insightxpert_api.config import Settings


def test_settings_loads_from_env(monkeypatch):
    """Settings ingests required env vars and honors documented defaults.

    Fields that may be overridden by a developer's ``.env.local`` (notably
    ``GEMINI_CHAT_MODEL``) are asserted only when explicitly monkeypatched —
    otherwise the test becomes flaky across machines with different envs.
    """
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
    s = Settings()
    assert s.session_ttl_seconds == 60 * 60 * 24 * 30
    assert s.max_upload_mb == 50
    assert s.gemini_chat_model == "gemini-2.5-flash"
    assert s.sql_row_limit == 1000
