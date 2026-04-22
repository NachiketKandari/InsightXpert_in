"""Application configuration loaded from env vars (or `.env.local` for dev)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
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

    # --- database connection pool ------------------------------------------
    # SQLAlchemy silently ignores pool_size / max_overflow / pool_timeout for
    # SQLite (which uses StaticPool / NullPool). These only take effect when
    # DATABASE_URL points at a Postgres (or other RDBMS) backend.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_pre_ping: bool = True

    # --- auth --------------------------------------------------------------
    session_secret: str
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days sliding
    session_cookie_name: str = "ix_session"

    # Bootstrap admin (applied once on first boot, then ignored if any user exists)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # Bootstrap regular user for local testing (optional; same idempotence as admin)
    bootstrap_user_email: str | None = None
    bootstrap_user_password: str | None = None

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

    # --- orchestration (B2) ------------------------------------------------
    # Read by the vendored orchestrator_loop — see agents_core/orchestrator.py.
    enable_stats_context: bool = False  # off by default in v1; no StatsResolver wired yet
    max_orchestrator_tasks: int = 10
    clarification_enabled: bool = False
    llm_provider: str = "gemini"

    # --- paths -------------------------------------------------------------
    bundled_dbs_dir: str = "./Databases"

    # --- profiling ---------------------------------------------------------
    # Columns per LLM call in the batched summary / quirk generators. One
    # prompt requests JSON keyed by column name. Drops summary-pass cost
    # from 2×columns LLM calls to ceil(columns / batch_size).
    profiling_batch_size: int = 20
    # Escape hatch — force the vendored per-column path (1 LLM call per
    # column per artifact). Expensive, kept as a safety valve.
    profiling_batch_disabled: bool = False
    # Hard cap above which all LLM-driven profiling stages auto-disable.
    # Wide DBs are rare (Snowflake landscape) and profiling them cost-free
    # is out of scope. The runner emits a warning if this fires.
    profiling_max_columns_for_llm: int = 500

    # --- Phase 1.4: rate limiting -----------------------------------------
    # Global LLM concurrency cap — see llm/gemini.py _llm_semaphore. One
    # user hammering chat cannot drive Gemini into 429 for everyone.
    llm_max_concurrency: int = 3
    # Profiling-specific semaphore. Stricter than the general cap because a
    # single 90-column profile = dozens of batched LLM calls.
    profile_max_concurrency: int = 2
    # Per-user daily cap on POST /databases/{id}/profile. When exceeded the
    # route returns HTTP 429 with a reset-time in the detail.
    profile_max_per_user_per_day: int = 10

    # --- automations (C1) --------------------------------------------------
    # Master switch. When false all automations/notifications routes are
    # unmounted and the scheduler lifespan hook is a no-op.
    automations_enabled: bool = False
    # "embedded" runs APScheduler inside the FastAPI process (local dev /
    # single-replica). "external" means scheduling comes from a cron hitting
    # POST /api/internal/run-due-automations with an HMAC-signed body.
    automations_scheduler_mode: str = "embedded"
    # Required (≥32 bytes) when mode=external; validated below.
    automations_scheduler_secret: str = ""
    # Embedded tick granularity in seconds — how often each job's cron trigger
    # is re-evaluated. Keep ≥5s to avoid pegging SQLite.
    automations_scheduler_tick_seconds: int = 30

    # --- observability: Sentry --------------------------------------------
    # Empty DSN → Sentry is a no-op (safe default for tests / fresh clones).
    # DSN itself is not secret (it's used in browser SDKs) but we still load
    # from env so production and local can target different projects.
    sentry_dsn: str = ""
    # Defaults to app_env when blank; explicit override wins.
    sentry_environment: str = ""
    sentry_release: str = ""
    # Traces sample rate — 0.0 disables performance tracing; 1.0 captures all.
    # Keep low in prod to control cost.
    sentry_traces_sample_rate: float = 0.0
    sentry_profiles_sample_rate: float = 0.0
    # Send PII (IP, headers, user email) with events. OFF by default; flip in
    # prod if your privacy posture allows.
    sentry_send_default_pii: bool = False

    @model_validator(mode="after")
    def _check_automations(self) -> Settings:
        if (
            self.automations_enabled
            and self.automations_scheduler_mode == "external"
            and len(self.automations_scheduler_secret) < 32
        ):
            raise ValueError(
                "AUTOMATIONS_SCHEDULER_SECRET must be >=32 bytes when "
                "AUTOMATIONS_SCHEDULER_MODE=external"
            )
        if self.automations_scheduler_mode not in ("embedded", "external"):
            raise ValueError(
                "AUTOMATIONS_SCHEDULER_MODE must be 'embedded' or 'external'"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: cached Settings instance.

    Tests that need to override env vars should clear this cache:
        get_settings.cache_clear()
    """
    return Settings()  # type: ignore[call-arg]
