from insightxpert_api.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GATE_PASSWORD", "pw")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    s = Settings()
    assert s.gate_password == "pw"
    assert s.session_ttl_seconds == 60 * 60 * 24 * 30
    assert s.max_upload_mb == 50
    assert s.gemini_chat_model == "gemini-2.5-flash"
    assert s.sql_row_limit == 1000
