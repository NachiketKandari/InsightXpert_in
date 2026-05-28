# InsightXpert.ai Architecture

InsightXpert.ai is a SaaS product: an AI-powered data analyst that lets users query their databases using plain English. This document covers the full system architecture -- deployment topology, backend internals, database layer, LLM integration, pipeline engine, streaming, auth, admin, and frontend subsystems.

---

## 1. System Overview

```
Browser (Next.js SPA)
  │
  │  GET /api/**       Firebase Hosting rewrites to Cloud Run
  │  POST /api/v1/chat SSE streaming
  │  POST /api/v1/auth/login
  ▼
Google Cloud Run (FastAPI)
  │
  ├─ Middleware: Sentry → CORS → GZip → Audit
  │
  ├─ Routers: health, auth, chat, databases, connections,
  │            sql, conversations, feedback, config, admin, ...
  │
  ├─ Pipeline: Profiler → SchemaLinker → SqlGenerator →
  │            SqlValidator → SqlExecutor → SqlRefiner → Synthesizer
  │
  ├─ Agentic Orchestrator: analyst → evaluate → DAG → synthesize
  │
  ├─ LLM Providers: Gemini + DeepSeek (provider-agnostic factory)
  │
  └─ Metadata DB (Postgres): users, databases, conversations, audit, ...
```

The system is deployed as two services:

- **Firebase Hosting** serves the Next.js static export. The `firebase.json` rewrites `GET /api/**` to the Cloud Run service in `us-central1`, so the browser makes same-origin calls to `/api/...` but Firebase transparently proxies them to Cloud Run without CORS preflight issues. All other paths fall through to `index.html` for client-side routing.

- **Google Cloud Run** runs the FastAPI backend container (`python:3.12-slim`). The `Dockerfile` installs dependencies via `uv` from `pyproject.toml`/`uv.lock`, copies the vendored code trees and prompt files, and exposes port `8080`.

In local development, Next.js (`next dev` on port 3000) proxies `/api/**` to `http://localhost:8000` via `next.config.js` rewrites, matching the Firebase production topology exactly.

---

## 2. Backend Application

### FastAPI App Factory

`apps/api/src/insightxpert_api/main.py` defines the application entry point. The module-level statement `app = create_app()` fires at import time. `create_app()` performs initialization in order:

1. **Settings load**: `get_settings()` reads all environment variables and `.env.local` into a `Settings` pydantic-settings model. The result is LRU-cached for zero-cost subsequent access.

2. **Sentry init**: `init_sentry(settings)` is called **before** `FastAPI()` is constructed. Sentry's `FastApiIntegration` patches at ASGI construction time. Silently no-ops when `SENTRY_DSN` is empty or `pytest` is in `sys.modules`.

3. **FastAPI construction**: The `FastAPI()` instance is created with `title="insightxpert.ai API"`, `version="0.1.0"`, and the `lifespan` context manager.

4. **Middleware registration** (in order):
   - **CORS** -- `allow_origins` from settings, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.
   - **GZip** -- compresses responses >= 1024 bytes.
   - **Audit** -- `AuditMiddleware` (BaseHTTPMiddleware) enqueues an `AuditRow` for non-GET requests after response.

   Sentry's `FastApiIntegration` patches at the ASGI level, running before all three.

5. **Router registration** (26+ routers mounted in order):
   ```
   health → auth → chat → databases → connections → sql →
   conversations → feedback → client_config → config →
   admin/* (users, overview, audit, metrics, conversations, prompts, RAG, databases) →
   shared snapshots → public shares → voice → sentry debug →
   internal → automations (conditional) → notifications (conditional) → /metrics
   ```

   Conditional routers (`automations`, `notifications`) are gated on `AUTOMATIONS_ENABLED`.

### Lifespan Handler

The `@asynccontextmanager` lifespan function manages startup and shutdown:

**Startup sequence:**
1. Settings loaded (hits LRU cache).
2. Logging configured via `configure_logging(settings.app_env)` -- structlog with ConsoleRenderer (local) or JSONRenderer (staging/prod).
3. Alembic migrations run to `head` inside `asyncio.to_thread()`.
4. Bootstrap users created (idempotent: admin + test user if none exist).
5. Audit queue started (`await _get_audit_queue().start()`).
6. Automations scheduler started (conditionally, if `AUTOMATIONS_ENABLED=true`).
7. SSE idle reaper launched as background `asyncio.Task` (evicts emitters idle >15 min every 60s).
8. **Yield** -- server now serves requests.

**Shutdown sequence:**
1. SSE reaper cancelled and awaited.
2. Audit queue stopped.
3. Automations scheduler stopped (if present).
4. Log `"api.stopping"`.

### Application State (`app.state`)

All shared services are attached to `app.state` during lifespan and accessed via `request.app.state` in route handlers. Key services include `settings`, LLM provider, database connectors, conversation store, dataset service, audit queue, and automation scheduler.

---

## 3. Database Architecture

### Two-Engine Pool

The app uses **two independent SQLAlchemy engine singletons** (`db/engine.py`):

| Engine | Pool Size | Overflow | Timeout | Used By |
|---|---|---|---|---|
| Request (`get_request_engine()`) | 15 | 10 | 10s | All HTTP route handlers |
| Background (`get_background_engine()`) | 2 | 0 | 30s | Automations scheduler/runner |

This prevents background work (automation polling, audit flushing) from starving user-facing requests. Both engines are lazily created on first access and share a single `DATABASE_URL`. A `reset_engine_cache()` test hook disposes both between tests.

### SQLAlchemy Core (Not ORM)

The project uses **SQLAlchemy Core** (Table objects on a shared `MetaData` instance), not the ORM. Table definitions use `sqlalchemy.Table(...)` with Column objects. Queries use `sqlalchemy.select()`, `insert()`, `update()`, `delete()` compiled through the Core.

This choice was deliberate:
- **No session management**: No `Session`/`sessionmaker`, no Unit of Work, no identity map. Queries execute directly against the engine.
- **Explicit transactions**: Every write path manages its own `engine.begin()` context.
- **Simpler async**: Raw connections with `run_in_thread` pattern instead of async ORM sessions.
- **Repository/Service split**: Repository modules own data access (raw SQLAlchemy Core queries). Service modules own business logic and call repositories.

### async_utils.py: run_in_thread Pattern

Since SQLAlchemy Core operations are synchronous (they block on I/O), all DB access runs in a thread pool:

```python
# async_utils.py
async def run_in_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)
```

Route handlers `await run_in_thread(repo.get_user, user_id)` instead of calling the repository directly. This prevents sync DB calls from blocking the event loop.

### Alembic Migrations

Schema evolution is managed by **Alembic** (`apps/api/alembic/`). Migrations run to `head` during lifespan startup, inside `asyncio.to_thread()`. There are 13+ migrations covering users, conversations, databases, audit, automations, profiles, and more.

For Postgres-backed deployments behind pgbouncer, Alembic uses a separate `DATABASE_DIRECT_URL` (bypassing the pooler) for migrations, since pgbouncer's transaction pooling is incompatible with Alembic's session-level DDL operations.

### Multi-Dialect (DialectAdapter Protocol)

User databases can be SQLite or Postgres. The `DialectAdapter` Protocol (`db/dialects/base.py`) provides four dispatch seams to avoid per-dialect branching at call sites:

1. **Connector open**: `open_readonly(ref)` returns a DB-API 2 connection.
2. **Schema extraction**: `extract_schema(db, ref)` returns table/column metadata.
3. **Validator parse**: `sqlglot_dialect` property for `sqlglot.transpile()`.
4. **Prompt selection**: `prompt_variant` resolves the Jinja template variant (e.g., `sql_generation.j2` vs `sql_generation_postgres.j2`).

Plus a `ProfilingQueryPack` for dialect-specific profiling SQL and `open_database()` for the profiling runner.

Each dialect is a single file in `db/dialects/` (`sqlite.py`, `postgres.py`). The registry at `db/dialects/__init__.py` dispatches `get_adapter(name: str) -> DialectAdapter`. **No call site ever branches on dialect name** -- every dispatch point calls `adapter.method(...)`.

Adding a third dialect (MySQL, BigQuery) requires one file implementing the Protocol, one registry import, and one prompt template variant. Zero existing code changes.

### Metadata DB vs. User DBs

**Metadata DB** (`DATABASE_URL`, typically Postgres/Supabase):
- Stores users, conversations, databases registry, audit logs, automations, profiles, prompts, insights.
- Managed by SQLAlchemy Core + Alembic.
- A shared `MetaData` instance holds all Table definitions.

**User DBs** (SQLite files / external Postgres):
- Accessed via `DatabaseConnector` (`db/connector.py`) using raw DB-API connections.
- **Write protection is belt-and-suspenders**:
  1. `FORBIDDEN_SQL_RE` regex blocks INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/REPLACE/MERGE/GRANT/REVOKE/ATTACH/DETACH before execution.
  2. `PRAGMA query_only = ON` (SQLite) or read-only connection (Postgres) set before every query, reset in `finally`.
- Multi-backend dispatch: `resolve_connector()` routes by database `kind` to the appropriate connector implementation.

---

## 4. Authentication and Authorization

### itsdangerous Signed Cookies (Not JWT)

Sessions use **itsdangerous** HMAC-signed cookies, not JWTs:

```python
from itsdangerous import URLSafeTimedSerializer

serializer = URLSafeTimedSerializer(settings.session_secret)
```

The serializer produces timestamped, cryptographically signed strings. The timestamp enables automatic expiry without a database round-trip.

### Session Flow

1. **Login** (`POST /api/v1/auth/login`):
   - Validates email + password using Argon2id.
   - Creates a session cookie: `serializer.dumps(user_id)`.
   - Sets the cookie as HTTP-only with `SameSite=Lax`, secure in production.
   - Cookie name: `ix_session` (configurable via `SESSION_COOKIE_NAME`).

2. **Issuing**: `create_session(response, user_id)` serializes the user ID with a timestamp and sets the `Set-Cookie` header.

3. **Verification** (every authenticated request):
   - `get_current_user` dependency reads the `ix_session` cookie.
   - `serializer.loads(cookie_value)` verifies the signature and checks expiry.
   - On signature failure or expiry: raises HTTP 401.
   - On success: extracts `user_id` from the payload.

4. **Validation**: The `user_id` is looked up from the metadata DB. The user row is checked for `is_active=True`.

### Dual Transport (Cookie + Bearer)

Sessions support two transport mechanisms:
- **Cookie**: `ix_session` HTTP-only cookie for browser requests.
- **Bearer token**: `Authorization: Bearer <token>` header for API clients, automation webhooks, and the shared-snapshot system.

Both use the same itsdangerous serializer and the same verification flow.

### sessions_valid_after Invalidation

Each user record has a `sessions_valid_after` timestamp. On password change, this field is updated to `now()`. During session validation, any session issued before `sessions_valid_after` is rejected. This enables global session invalidation without maintaining a token blocklist.

### Argon2id Password Hashing

Passwords are hashed using **Argon2id** (via the `argon2-cffi` package), not bcrypt:

```python
from argon2 import PasswordHasher
ph = PasswordHasher()
hash = ph.hash(password)
ph.verify(hash, password)
```

Argon2id is memory-hard and resistant to GPU/ASIC attacks. The `argon2-cffi` defaults (time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16) are used.

### User Cache (30s TTL)

A per-request user cache with 30-second TTL avoids repeated DB lookups for the same user within a request lifecycle. `get_current_user` checks the cache before querying the DB.

### Admin Access

Admin access is determined by `user.is_admin` flag or by the user's email domain matching configured `admin_domains`. Admin-only endpoints use the `require_admin` dependency which raises HTTP 403 for non-admin users.

---

## 5. Configuration

### pydantic-settings BaseSettings

`Settings` in `config.py` is a `pydantic-settings.BaseSettings` model reading from `.env.local` (resolved relative to `apps/api/`). Every configuration value is declared as a typed field with a default:

```python
class Settings(BaseSettings):
    app_env: str = "local"
    database_url: str = "sqlite:///./app.db"
    session_secret: str = ...
    gemini_api_key: str = ...
    # ... 50+ fields
```

### LRU-Cached get_settings()

`get_settings()` is decorated with `@lru_cache(maxsize=1)`. The first call parses env vars and `.env.local`; subsequent calls return the cached instance. Tests call `get_settings.cache_clear()` to reset between test cases.

### Environment Categories

Configuration is organized into logical groups:

| Category | Key Variables |
|---|---|
| **Runtime** | `APP_ENV`, `PORT`, `CORS_ORIGINS`, `DATABASE_URL` |
| **Connection Pool** | `DB_POOL_SIZE` (15), `DB_MAX_OVERFLOW` (10), `DB_BACKGROUND_POOL_SIZE` (2) |
| **Auth** | `SESSION_SECRET`, `SESSION_TTL_SECONDS` (30d), `BOOTSTRAP_ADMIN_EMAIL` |
| **LLM** | `GEMINI_API_KEY`, `GEMINI_CHAT_MODEL`, `DEEPSEEK_API_KEY`, `LLM_PROVIDER` |
| **Profiling** | `PROFILING_BATCH_SIZE` (20), `PROFILING_MAX_COLUMNS_FOR_LLM` (500), `LLM_MAX_CONCURRENCY` (3) |
| **Pipeline** | `SQL_ROW_LIMIT` (1000), `SQL_TIMEOUT_SECONDS` (30), `MAX_REFINEMENT_ITERATIONS` (2) |
| **Automations** | `AUTOMATIONS_ENABLED`, `AUTOMATIONS_SCHEDULER_MODE` |
| **Observability** | `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` |

All sensitive features (Sentry, automations, voice, credential encryption) default to disabled/empty.

---

## 6. Observability

### Structured Logging

**structlog** with processors: `merge_contextvars`, `add_log_level`, `TimeStamper(fmt="iso", utc=True)`, `StackInfoRenderer`.

- **Local dev** (`APP_ENV=local`): ConsoleRenderer (pretty, colorized).
- **Production** (`APP_ENV=staging|prod`): JSONRenderer (Cloud Logging-compatible JSON lines).

Filter: `logging.INFO` level.

### Sentry Error Tracking

`init_sentry(settings)` in `sentry.py` is called **before** `FastAPI()` construction:

- Integrations: `FastApiIntegration`, `StarletteIntegration`, `AsyncioIntegration`, `LoggingIntegration`.
- No-ops when `SENTRY_DSN=""` or pytest is in `sys.modules`.
- Performance sampling: `SENTRY_TRACES_SAMPLE_RATE` (default 0.0), `SENTRY_PROFILES_SAMPLE_RATE` (default 0.0).
- PII: `SENTRY_SEND_DEFAULT_PII` (default `False`).

### Prometheus Metrics

The `/metrics` endpoint exposes in-memory counters (with `threading.Lock`):

| Metric | Description |
|---|---|
| `audit_queue_depth` | Current audit queue size |
| `audit_overflow_total` | Audit entries dropped due to queue overflow |
| `sse_active_emitters` | Currently open SSE connections |
| `sse_evicted_total` | SSE emitters evicted by idle reaper |
| `llm_calls_total{source=...}` | LLM call count by source |
| `process_resident_memory_bytes` | Process memory usage |
| `process_open_fds` | Open file descriptors |

### SLA/SLO Tracking

Histograms and counters track request latency by tier (Critical, Standard, Background). Route-to-tier mapping classifies endpoints. P95 targets: Critical < 2s, Standard < 10s.

---

## 7. Audit System

### Async Batching Queue

The `AuditMiddleware` enqueues an `AuditRow` for every non-GET request. A background `asyncio.Task` drains the queue:

- **Batch size**: 50 rows per flush.
- **Flush interval**: 200ms.
- **Capacity**: 5000 entries (oldest-drop when full).
- **Classification**: Regex path matching derives `(resource_type, resource_id)`.

The audit system never raises -- failures are logged and swallowed. The audit loop is started during lifespan startup and gracefully stopped during shutdown.

---

## 8. Key Design Decisions

### Protocol-Based Adapters (Not ABC)

Two core adapter patterns use `typing.Protocol` with `@runtime_checkable`:
- **Stage Protocol**: `Stage` with `name: str` and `async def run(self, ctx, input) -> Any`.
- **DialectAdapter Protocol**: `DialectAdapter` with `open_readonly()`, `extract_schema()`, `sqlglot_dialect`, `prompt_variant`, and 5 more methods.

Protocols enable structural subtyping -- vendored classes satisfy the contract without inheriting from our base classes.

### Vendored Code Pattern

Two code trees are vendored at `apps/api/src/insightxpert_api/vendored/`:
- **`pipelines_core`** (from Private/InsightXpert): Schema extraction, profiling, linking, generation, refinement, evaluation.
- **`agents_core`** (from public/InsightXpert): Orchestration, agent loops, tool systems, RAG, prompts.

Neither tree is edited directly. Project-original code wraps vendored classes in stage implementations, adding SSE emissions, error handling, and batched profiling. Changes to vendored code are applied as patches via `apps/api/scripts/vendored_patches/`.

### In-Process Caches (No Redis)

All caching is in-process:
- **Settings**: `@lru_cache(maxsize=1)` on `get_settings()`.
- **User cache**: 30s TTL per-request dictionary.
- **DatabaseProfile cache**: Process-level dict in `ProfileService` (invalidated on profile save).
- **Conversation store**: Thread-safe `OrderedDict` with LRU eviction (max 500 conversations).

No Redis dependency means simpler deployment and zero network latency for cache access. The trade-off is that caches are lost on instance recycle (acceptable for v1).

### Conditional Router Mounting

Automations and notifications routers are conditionally mounted via `AUTOMATIONS_ENABLED`. When disabled, the routes don't exist at all (they don't return 404 or 503 -- they are absent from the app). This avoids deploying dead code paths.

### Lazy Engine Singletons

Both request and background SQLAlchemy engines are created on first access, not at import time. This means tests can set environment variables after import and before engine creation, and the app can start without a database connection (e.g., for health checks during deploy).

### UUID4 Hex IDs

All entity IDs use `uuid.uuid4().hex` (32-character hex strings). No hyphens, no collisions, no sequential enumeration. Examples: `conversation_id`, `message_id`, `user_id`, `db_id`.

### Epoch Timestamps

All timestamps are Unix epoch floats (seconds). The `created_at` field on every table uses `time.time()`. This avoids timezone ambiguity and simplifies comparison/sorting in both Python and JavaScript.

---

## 9. Frontend Architecture

The Next.js frontend (`apps/web/`) uses the App Router with TypeScript.

### Layout
- `app/layout.tsx` -- Root layout with providers (auth, theme).
- `components/layout/app-shell.tsx` -- Three-column layout: left sidebar (conversation list), center (chat panel), right sidebar (agent process steps).

### Chat
- `components/chat/chat-panel.tsx` -- Orchestrates the chat UI; owns SSE connection.
- `components/chat/message-list.tsx` -- Virtualized message list with auto-scroll.
- `components/chat/message-bubble.tsx` -- Per-message container; delegates chunk rendering.
- `components/chat/message-input.tsx` -- Textarea with submit; handles clarification paths.
- `components/chunks/chunk-renderer.tsx` -- Dispatches `ChatChunk.type` to the correct chunk component.

### Chunk Components
Each SSE chunk type maps to a dedicated React component:

| Component | Chunk types |
|---|---|
| `status-chunk.tsx` | `status` |
| `tool-call-chunk.tsx` | `tool_call` |
| `sql-chunk.tsx` | `sql_generated` |
| `tool-result-chunk.tsx` | `tool_result`, `rows_returned` |
| `answer-chunk.tsx` | `answer_generated`, `answer_delta` |
| `insight-chunk.tsx` | `insight` |
| `stats-context-chunk.tsx` | `stats_context` |
| `clarification-chunk.tsx` | `clarification` |
| `error-chunk.tsx` | `error` |
| `thinking-trace.tsx` | `agent_trace`, `orchestrator_plan` |
| `trace-modal.tsx` | Expandable modal for enrichment traces |
| `citation-link.tsx` | Inline `[^N]` citation in insight text |

### Stores
Zustand stores manage global client state: auth store, conversation store, notification store.

### SSE Client
`lib/sse-client.ts` reads the streaming response via `fetch()` + `ReadableStream`, parses `data:` lines into `ChatChunk` objects, and dispatches to a callback. React 18's automatic batching means multiple consecutive chunks are batched into a single re-render.
