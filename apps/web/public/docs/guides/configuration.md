# InsightXpert.ai Configuration Reference

The backend reads configuration from `apps/api/.env.local` via **pydantic-settings** (`BaseSettings`). All values can also be set as regular shell environment variables; environment variables take precedence over `.env.local`.

The settings class is `insightxpert_api.config.Settings`. A fresh `.env.local` can be seeded from `apps/api/.env.example`.

---

## Configuration Architecture

**`Settings`** in `config.py` is a `pydantic_settings.BaseSettings` model reading from `.env.local` (resolved relative to `apps/api/`). The `get_settings()` function is an **LRU-cached singleton** (`@lru_cache(maxsize=1)`). All application code calls `get_settings()` rather than instantiating `Settings()` directly.

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )
    # ... fields ...

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

**Key behaviors:**
- `extra="ignore"` -- unknown env vars are silently discarded
- `case_sensitive=False` -- env vars are matched case-insensitively
- `.env.local` is resolved relative to `apps/api/`, making it stable regardless of launch CWD
- Tests call `get_settings.cache_clear()` to reset after overriding env vars

---

## 1. Runtime Settings

| Env Var | Default | Description |
|---|---|---|
| `APP_ENV` | `"local"` | Deployment environment: `local`, `staging`, or `prod`. Controls logging format (ConsoleRenderer for local, JSONRenderer for staging/prod) and Sentry env fallback. |
| `PORT` | `8080` | HTTP listen port. |
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:3001"]` | Allowed CORS origins as a JSON array. CORS middleware sets `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. |

---

## 2. Authentication Settings

| Env Var | Default | Description |
|---|---|---|
| `SESSION_SECRET` | _(required)_ | Secret key for signing session cookies. Must be at least 32 characters. Rotating this key invalidates all existing sessions. |
| `SESSION_TTL_SECONDS` | `2592000` (30 days) | Sliding session expiration. The cookie's `Max-Age` is set to this value on every authenticated request. |
| `SESSION_COOKIE_NAME` | `"ix_session"` | Name of the HttpOnly session cookie. |
| `BOOTSTRAP_ADMIN_EMAIL` | `None` | Admin email created on first boot if no users exist. Idempotent -- skipped if any user already exists. |
| `BOOTSTRAP_ADMIN_PASSWORD` | `None` | Password for the bootstrap admin account. |
| `BOOTSTRAP_USER_EMAIL` | `None` | Test user email created on first boot. |
| `BOOTSTRAP_USER_PASSWORD` | `None` | Password for the bootstrap test user. |

**Auth mechanism:** itsdangerous `URLSafeTimedSerializer` with HMAC-SHA256 signing. Sessions are stored in cookies (HttpOnly, SameSite=Lax, Secure in non-local environments). A `Bearer` header fallback accepts the same signed token for SSE and WebSocket endpoints. Password hashing uses Argon2id via `argon2-cffi`.

Session invalidation is handled via the `sessions_valid_after` timestamp on the user row -- any session issued before that timestamp is rejected. This allows admins to force-logout all sessions for a user by updating the timestamp.

---

## 3. Database Settings

### Primary Metadata Database

| Env Var | Default | Description |
|---|---|---|
| `DATABASE_URL` | `"sqlite:///./app.db"` | Primary metadata DB connection string. Supports SQLite (`sqlite:///...`) and Postgres (`postgresql+psycopg://...`). This stores users, conversations, databases registry, audit logs, automations, profiles, etc. |
| `DATABASE_DIRECT_URL` | `""` | Direct (non-pooler) connection URL for Alembic migrations. Falls back to `DATABASE_URL` when unset. Required because pooler transaction mode is incompatible with DDL operations. |

### Connection Pool (Postgres only)

Two independent SQLAlchemy engine singletons isolate request-serving from background work, preventing hung background tasks from starving user requests.

**Request Engine** (serves all HTTP route handlers):

| Env Var | Default | Description |
|---|---|---|
| `DB_POOL_SIZE` | `15` | Number of persistent connections. |
| `DB_MAX_OVERFLOW` | `10` | Additional connections allowed beyond pool_size. |
| `DB_POOL_TIMEOUT` | `10` | Seconds to wait for a connection before raising `TimeoutError`. |
| `DB_POOL_PRE_PING` | `False` | Check connection liveness on checkout. Keep `False` for pgbouncer (transaction pooler handles dead connections). |
| `DB_POOL_RECYCLE` | `600` | Max connection age in seconds before recycling. |
| `DB_CONNECT_TIMEOUT` | `10` | Connection establishment timeout. |

**Background Engine** (automations scheduler/runner):

| Env Var | Default | Description |
|---|---|---|
| `DB_BACKGROUND_POOL_SIZE` | `2` | Persistent connections for background tasks. |
| `DB_BACKGROUND_MAX_OVERFLOW` | `0` | No overflow -- background work is capped. |
| `DB_BACKGROUND_POOL_TIMEOUT` | `30` | More generous timeout for background operations. |

**Pool settings are silently ignored by SQLite** (which uses StaticPool/NullPool internally). They only take effect when `DATABASE_URL` points at a Postgres backend.

### Database Connection Strings

**Transaction Pooler (Supabase port 6543)** -- for runtime queries:
```
DATABASE_URL=postgresql+psycopg://postgres.<project_ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```
Note the user format is `postgres.<project_ref>` (required by the pooler), not just `postgres`.

**Direct Connection (Supabase port 5432)** -- for Alembic migrations:
```
DATABASE_DIRECT_URL=postgresql+psycopg://postgres:<password>@db.<project_ref>.supabase.co:5432/postgres?sslmode=require
```

**pgBouncer awareness:** When Postgres is detected, the engine is configured for pgbouncer transaction mode: `pool_pre_ping=False`, prepare statements disabled via `connect_args`. This avoids session-level features that conflict with transaction pooling.

**SQLite behavior:** `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON` are set via SQLAlchemy connect event listeners.

### User Database Access

User databases (uploaded SQLite files or external Postgres connections) are accessed via `DatabaseConnector`, which enforces:
- `PRAGMA query_only = ON` (SQLite) or `default_transaction_read_only=on` (Postgres) before every query
- Regex block on `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/REPLACE/MERGE/GRANT/REVOKE/ATTACH/DETACH`
- Statement timeout via `SQL_TIMEOUT_SECONDS`

---

## 4. LLM Provider Configuration

### Gemini (Google AI Studio)

| Env Var | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | _(required)_ | Google AI Studio API key. Obtain at https://aistudio.google.com/app/apikey |
| `GEMINI_CHAT_MODEL` | `"gemini-2.5-flash"` | Model used for chat/completion. Available: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite`, `gemini-2.0-flash`, `gemini-2.0-flash-lite`. |
| `GEMINI_EMBED_MODEL` | `"gemini-embedding-001"` | Model used for embeddings (RAG, pgvector). |

### DeepSeek (OpenAI-compatible API)

| Env Var | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | `""` | DeepSeek API key. Empty = DeepSeek disabled. |
| `DEEPSEEK_CHAT_MODEL` | `"deepseek-v4-flash"` | DeepSeek chat model. |

### Provider Selection

| Env Var | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `"deepseek"` | Which provider the orchestrator uses: `"gemini"` or `"deepseek"`. Can be switched at runtime via `POST /api/v1/config/switch` (in-process only, lost on restart). |

When DeepSeek is the chat provider, embeddings still go to Gemini (DeepSeek has no embedding API). `GEMINI_API_KEY` must still be set.

### Concurrency Controls

| Env Var | Default | Description |
|---|---|---|
| `LLM_MAX_CONCURRENCY` | `3` | Global LLM call semaphore. Prevents one user from driving the provider into 429 for everyone. |
| `PROFILE_MAX_CONCURRENCY` | `2` | Profiling-specific semaphore. Stricter because a single profile can trigger dozens of batched LLM calls. |

---

## 5. Pipeline Tuning

| Env Var | Default | Description |
|---|---|---|
| `MAX_UPLOAD_MB` | `50` | Max database upload size in MB. Enforced via chunked read; returns 413 on oversize. |
| `SQL_ROW_LIMIT` | `1000` | Max rows returned by any user-facing SQL query. Applies to chat pipeline and `POST /api/v1/sql/execute`. |
| `SQL_TIMEOUT_SECONDS` | `30` | Max execution time for a single SQL query. Maps to `SQLTimeoutError` -> 408. |
| `MAX_REFINEMENT_ITERATIONS` | `2` | Max SQL refinement loops when the validator detects errors. |
| `ENABLE_STATS_CONTEXT` | `False` | Inject pre-computed dataset statistics into the system prompt. Off by default in v1. |
| `MAX_ORCHESTRATOR_TASKS` | `10` | Max concurrent sub-tasks the DAG orchestrator can spawn per question. |
| `CLARIFICATION_ENABLED` | `False` | Whether the orchestrator may ask clarifying questions before proceeding. |

---

## 6. Profiling Configuration

| Env Var | Default | Description |
|---|---|---|
| `PROFILING_BATCH_SIZE` | `20` | Columns per LLM call in the batched summary/quirk generators. Reduces cost from 2x N calls to ceil(N / BATCH_SIZE) per artifact. |
| `PROFILING_BATCH_DISABLED` | `False` | Escape hatch -- forces the old per-column path (1 LLM call per column per artifact). Expensive, kept as a safety valve. |
| `PROFILING_MAX_COLUMNS_FOR_LLM` | `500` | Hard cap above which all LLM-driven profiling stages auto-disable. Wide DBs (e.g., Snowflake landscapes) skip cost-free. |
| `PROFILE_MAX_PER_USER_PER_DAY` | `10` | Per-user daily cap on `POST /databases/{id}/profile`. Returns 429 when exceeded. Admins exempt. |

---

## 7. Automations Setup

| Env Var | Default | Description |
|---|---|---|
| `AUTOMATIONS_ENABLED` | `False` | Master switch. When `False`, all automations/notifications routes are unmounted and the scheduler lifespan hook is a no-op. |
| `AUTOMATIONS_SCHEDULER_MODE` | `"embedded"` | `"embedded"` runs APScheduler inside the FastAPI process (dev/single-replica). `"external"` expects a cron job hitting `POST /api/internal/run-due-automations` with an HMAC-signed body. |
| `AUTOMATIONS_SCHEDULER_SECRET` | `""` | HMAC secret (minimum 32 characters) required when `mode=external`. Validated at startup; raises `ValueError` if too short. |
| `AUTOMATIONS_SCHEDULER_TICK_SECONDS` | `30` | Tick interval for the embedded APScheduler. Keep >=5s to avoid excessive DB load. |
| `AUTOMATIONS_MAX_PER_USER` | `50` | Per-user cap on the number of automations. Enforced atomically via `pg_advisory_xact_lock` (Postgres) or write-lock (SQLite). Returns 429 when exceeded. |

**Dispatching:** Due automations are claimed via `SELECT ... FOR UPDATE SKIP LOCKED`, making the system safe for multi-replica deployments.

---

## 8. Sentry Configuration

| Env Var | Default | Description |
|---|---|---|
| `SENTRY_DSN` | `""` | Sentry DSN. Empty = Sentry is a no-op (safe default for tests/fresh clones). Also no-ops when `pytest` is in `sys.modules`. |
| `SENTRY_ENVIRONMENT` | `""` | Sentry environment tag. Defaults to `APP_ENV` when blank. |
| `SENTRY_RELEASE` | `""` | Git SHA or semantic release string for grouping events per release. |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Performance tracing sample rate. 0.0 disables, 1.0 captures all. Keep low in prod to control cost. |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.0` | Profiling sample rate. |
| `SENTRY_SEND_DEFAULT_PII` | `False` | Include IP, headers, and user email in captured events. Off by default. |

**Initialization order:** Sentry is initialized in `create_app()` **before** `FastAPI()` construction, so integrations (`FastApiIntegration`, `StarletteIntegration`, `AsyncioIntegration`, `LoggingIntegration`) patch at the ASGI level before any middleware or routers are registered.

---

## 9. Storage Configuration

| Env Var | Default | Description |
|---|---|---|
| `GCS_BUCKET` | `""` | Google Cloud Storage bucket name for uploaded files. Empty = local filesystem fallback (dev/tests). |
| `LOCAL_STORAGE_DIR` | `"./tmp/storage"` | Local directory for file storage when `GCS_BUCKET` is empty. |
| `BUNDLED_DBS_DIR` | `"./Databases"` | Directory containing bundled sample databases. |

---

## 10. Voice / Speech-to-Text

| Env Var | Default | Description |
|---|---|---|
| `DEEPGRAM_API_KEY` | `""` | Deepgram Nova-3 API key. Empty = voice feature disabled. If a client connects to `/api/transcribe` without this key set, the WebSocket is closed with code 4002. Obtain at https://console.deepgram.com/ |

---

## 11. Credential Encryption (BYO DB)

| Env Var | Default | Description |
|---|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` | `None` | Fernet symmetric key (32-byte URL-safe base64) for encrypting BYO database credentials at rest. Only required when `/api/v1/connections` is used. Generate with: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |

---

## 12. SLA Thresholds

| Env Var | Default | Description |
|---|---|---|
| `SLA_CRITICAL_P95_MS` | `300` | p95 latency target for critical routes (login, chat). |
| `SLA_STANDARD_P95_MS` | `500` | p95 latency target for standard routes (conversations, databases). |
| `SLA_BACKGROUND_P95_MS` | `2000` | p95 latency target for background/admin routes. |

---

## 13. Feature Flags

The `AUTOMATIONS_ENABLED` flag controls **conditional route mounting**. When `False`, the automations and notifications routers are never registered with FastAPI. This means:
- All `/api/v1/automations/*` routes return 404
- All `/api/v1/notifications/*` routes return 404
- The SSE notification stream is unavailable
- The scheduler lifespan hook is a no-op
- The internal HMAC endpoint returns 503

The `/api/v1/client-config` endpoint reflects this in its `features` map:
```json
{
  "features": {
    "sql_runner": true,
    "upload": true,
    "profile_editor": true,
    "voice": true,
    "automations": false,
    "admin": false,
    "insights": true,
    "notifications": false
  },
  "version": "0.1.0"
}
```

---

## 14. Observability

The observability stack consists of three layers:

1. **structlog** (structured logging) -- ConsoleRenderer for local dev (pretty, colorized), JSONRenderer for staging/prod (Cloud Logging compatible lines). Controlled by `APP_ENV`.

2. **Sentry** (error tracking) -- Initialized before FastAPI construction. Integrations: `FastApiIntegration`, `StarletteIntegration`, `AsyncioIntegration`, `LoggingIntegration`. See Section 8 for configuration.

3. **Prometheus** (metrics) -- In-memory counters exposed at `GET /metrics` (no auth). Counters include `audit_queue_depth`, `sse_active_emitters`, `llm_calls_total`, `process_resident_memory_bytes`. Per-endpoint latency histograms via `http_request_duration` and `db_query_duration`.

**Audit middleware** enqueues an audit row for every non-GET request, classifying paths against a regex table to derive `(resource_type, resource_id)`. Audit rows are drained in batches (50 rows / 200ms, max 5000 entries). Audit failures are logged and swallowed -- they never impact the response.

---

## 15. Development vs Production Settings

### Minimal Local Development `.env.local`

```dotenv
APP_ENV=local
PORT=8080

# Auth (generate a real secret for anything beyond localhost)
SESSION_SECRET=local-dev-secret-at-least-32-characters-long!!

# Bootstrap users (idempotent -- only applied on first boot)
BOOTSTRAP_ADMIN_EMAIL=admin@insightxpert.ai
BOOTSTRAP_ADMIN_PASSWORD=admin123
BOOTSTRAP_USER_EMAIL=user@insightxpert.ai
BOOTSTRAP_USER_PASSWORD=user@insightxpert.ai123

# Database (SQLite for local dev -- no Postgres needed)
DATABASE_URL=sqlite:///./app.db

# LLM (choose one provider)
LLM_PROVIDER=deepseek
GEMINI_API_KEY=your-gemini-key
DEEPSEEK_API_KEY=your-deepseek-key

# Pipeline
MAX_UPLOAD_MB=50
SQL_ROW_LIMIT=1000
SQL_TIMEOUT_SECONDS=30

# Optional: enable automations for local testing
# AUTOMATIONS_ENABLED=true
# AUTOMATIONS_SCHEDULER_MODE=embedded
```

### Production Considerations

For production deployments on Cloud Run:

- **Database:** Use Supabase Postgres with the transaction pooler URL (port 6543) for `DATABASE_URL`. Set `DATABASE_DIRECT_URL` (port 5432) for Alembic migrations. Tune pool sizes: `DB_POOL_SIZE=15`, `DB_MAX_OVERFLOW=10`.
- **Session secret:** Generate a strong random string of 32+ characters. Rotating this invalidates all sessions.
- **Bootstrap passwords:** Change from defaults. They are only applied on first boot but should still be strong in case the DB is ever reset.
- **Sentry:** Set `SENTRY_DSN` to your project DSN. Start with `SENTRY_TRACES_SAMPLE_RATE=0.1` and adjust based on cost.
- **Automations:** If using external scheduler, set `AUTOMATIONS_SCHEDULER_MODE=external` and provide a strong `AUTOMATIONS_SCHEDULER_SECRET` (32+ random bytes).
- **CORS:** Set `CORS_ORIGINS` to your production frontend origins as a JSON array.
- **Credential encryption:** Generate a Fernet key and set `CREDENTIAL_ENCRYPTION_KEY` if BYO database connections will be used.
- **Storage:** Set `GCS_BUCKET` to your GCS bucket name for persistent file storage.
- **Logging:** Set `APP_ENV=prod` for JSON-formatted structlog output.
