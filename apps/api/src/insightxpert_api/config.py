"""Application configuration loaded from env vars (or `.env.local` for dev)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven settings. Fields here are load-bearing; don't add unused config."""

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- runtime -----------------------------------------------------------
    app_env: str = "local"  # local | staging | prod
    port: int = 8080
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    database_url: str = "sqlite:///./app.db"

    # --- auth --------------------------------------------------------------
    gate_password: str
    session_secret: str
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days sliding
    session_cookie_name: str = "ix_session"

    # Bootstrap admin (applied once on first boot, then ignored if any user exists)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- llm ---------------------------------------------------------------
    gemini_api_key: str
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"

    # --- storage -----------------------------------------------------------
    gcs_bucket: str = ""  # empty → local-fs fallback (dev/tests)
    local_storage_dir: str = "./tmp/storage"

    # --- pipeline ----------------------------------------------------------
    max_upload_mb: int = 50
    sql_row_limit: int = 1000
    sql_timeout_seconds: int = 30
    max_refinement_iterations: int = 2

    # --- paths -------------------------------------------------------------
    bundled_dbs_dir: str = "./Databases"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: cached Settings instance.

    Tests that need to override env vars should clear this cache:
        get_settings.cache_clear()
    """
    return Settings()  # type: ignore[call-arg]
