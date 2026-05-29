"""Application configuration loaded from env vars (or `.env.local` for dev)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor `.env.local` to the api package root so launches from any cwd
# (repo root via turbo, apps/api via uv, etc.) all resolve the same file.
_API_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _API_ROOT / ".env.local"


class Settings(BaseSettings):
    """Env-driven settings. Fields here are load-bearing; don't add unused config."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- runtime -----------------------------------------------------------
    app_env: str = "local"  # local | staging | prod
    port: int = 8080
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
        ]
    )
    # DECISION(D-041): Supabase managed Postgres for metadata — pgvector support,
    # built-in pgbouncer (transaction pooler on port 6543), PG 17.6.
    # DATABASE_URL points to pooler for runtime; DATABASE_DIRECT_URL (port 5432)
    # for Alembic migrations.
    database_url: str = "sqlite:///./app.db"

    # --- database connection pool ------------------------------------------
    # Two engines, two pools. The request engine serves HTTP route handlers;
    # the background engine serves the automations scheduler / runner. Sizing
    # them separately means a hung background tick cannot starve user
    # requests by exhausting the pool.
    #
    # SQLAlchemy silently ignores pool_size / max_overflow / pool_timeout for
    # SQLite (which uses StaticPool / NullPool). These only take effect when
    # DATABASE_URL points at a Postgres (or other RDBMS) backend.
    db_pool_size: int = 15
    db_max_overflow: int = 10
    db_pool_timeout: int = 10
    db_pool_pre_ping: bool = False  # transaction pooler handles dead conns
    db_pool_recycle: int = 600
    db_connect_timeout: int = 10

    db_background_pool_size: int = 2
    db_background_max_overflow: int = 0
    db_background_pool_timeout: int = 30

    # Optional direct (non-pooler) URL — used by Alembic migrations and any
    # ops script that needs session-level features. Falls back to
    # database_url when unset.
    database_direct_url: str = ""

    # --- auth --------------------------------------------------------------
    session_secret: str
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days sliding
    session_cookie_name: str = "ix_session"
    # Cross-subdomain cookie sharing (www ↔ api). Only set in prod/staging.
    # Leading dot = all subdomains. Leave empty for local dev.
    cookie_domain: str = ""

    # Bootstrap admin (applied once on first boot, then ignored if any user exists)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # Bootstrap regular user for local testing (optional; same idempotence as admin)
    bootstrap_user_email: str | None = None
    bootstrap_user_password: str | None = None

    # Public registration gate — set false to disable self-signup
    registration_enabled: bool = True

    # Auth endpoints rate limiting (per-IP requests per minute)
    auth_rate_limit_per_minute: int = 10
    auth_rate_limit_enabled: bool = True

    # --- llm ---------------------------------------------------------------
    gemini_api_key: str
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"

    deepseek_api_key: str = ""
    deepseek_chat_model: str = "deepseek-v4-flash"

    # --- voice / speech-to-text -------------------------------------------
    # Deepgram Nova-3 streaming. Empty → /api/transcribe closes with 4002.
    deepgram_api_key: str = ""

    # --- storage -----------------------------------------------------------
    gcs_bucket: str = ""  # empty → local-fs fallback (dev/tests)
    local_storage_dir: str = "./tmp/storage"

    # --- pipeline ----------------------------------------------------------
    max_upload_mb: int = 50
    sql_row_limit: int = 1000
    sql_timeout_seconds: int = 30
    max_refinement_iterations: int = 2
    single_sql_column_threshold: int = 25

    # --- orchestration (B2) ------------------------------------------------
    # Read by the vendored orchestrator_loop — see agents_core/orchestrator.py.
    clarification_enabled: bool = False
    llm_provider: str = "deepseek"
    enable_stats_context: bool = True
    max_orchestrator_tasks: int = 10
    max_agent_iterations: int = 25
    max_quant_analyst_iterations: int = 15

    # --- paths -------------------------------------------------------------
    bundled_dbs_dir: str = "./Databases"
    # Per-DB profiling artifacts (LSH, vector, join graph). Built during
    # profiling and loaded at query time by SchemaLinkerStage.
    indices_dir: str = "./indices"

    # --- profiling ---------------------------------------------------------
    # Columns per LLM call in the batched summary / quirk generators. One
    # prompt requests JSON keyed by column name. Drops summary-pass cost
    # from 2 * columns LLM calls to ceil(columns / batch_size).
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
    # Per-user cap on the number of automations a single user may own. When
    # exceeded, POST /api/v1/automations returns HTTP 429.
    automations_max_per_user: int = 50

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

    # --- connection credential encryption (BYO external DB) --------------
    # Fernet symmetric key (32-byte url-safe base64). Only required when the
    # /api/v1/connections routes are exercised (saving an external DB conn).
    # Generate: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    credential_encryption_key: str | None = None

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


# DECISION(D-032): LRU-cached singleton Settings — @lru_cache on get_settings() instead of dependency injection
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency: cached Settings instance.

    Tests that need to override env vars should clear this cache:
        get_settings.cache_clear()
    """
    return Settings()  # type: ignore[call-arg]
