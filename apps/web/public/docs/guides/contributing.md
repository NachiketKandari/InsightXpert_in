# Contributing Guide

This guide covers how to set up, develop, and contribute to InsightXpert.ai -- a SaaS AI data analyst that lets users query databases using plain English.

---

## Project Structure

InsightXpert.ai is a **Turborepo monorepo** with npm workspaces for the frontend and `uv` for the Python backend.

```
insightxpert.ai/
  apps/
    api/                          # Python 3.12 + FastAPI backend
      src/insightxpert_api/
        admin/                    # Admin overview cache, feature toggles
        agents/                   # Agent implementations (vendored orchestrator)
        audit/                    # Audit logging middleware + queue
        auth/                     # Session signer, current_user dependency
        automations/              # Schedule runner, trigger evaluator, notifications
        connections/              # BYO external DB: Postgres connector, Fernet encryption
        databases/                # DB registry: CRUD, visibility, profiling
        db/                       # SQLAlchemy engines, DatabaseConnector, dialects/
        insights/                 # Insights API routes
        jobs/                     # Async job wrappers (sample questions)
        llm/                      # Provider factory: Gemini + DeepSeek
        metrics/                  # Per-turn query metrics, cost tracking
        middleware/               # Audit middleware, CORS
        orchestration/            # Conversations, messages, insights, agent traces
        pipeline/                 # Pipeline stages wrapping vendored pipeline_core
        profiling/                # 7-stage profile runner with SSE + batched LLM
        prompts/                  # DB-first prompt template resolver
        rag/                      # pgvector-backed vector store
        routes/                   # All route files (chat, databases, admin, etc.)
        sample_questions/         # 7-stage sample question generation pipeline
        scripts/                  # Bootstrap and maintenance scripts
        services/                 # Cross-cutting services
        shared_snapshots/         # Chat sharing via capability URLs
        sse/                      # EventEmitter + SSE chunk envelope
        storage/                  # Object storage: GCS + local FS
        users/                    # User CRUD, Argon2id hashing, bootstrapping
        vendored/                 # Immutable vendored code (pipeline_core, agents_core)
      tests/                      # pytest test suite (~280+ tests)
      alembic/                    # Database migrations
      pyproject.toml
    web/                          # Next.js 15+ frontend
      src/
        app/                      # App Router pages (chat, login, admin, automations, etc.)
        components/               # React components organized by domain
        hooks/                    # Custom React hooks
        lib/                      # Utility libraries, SSE client, API helpers
        stores/                   # Zustand stores
        types/                    # TypeScript type definitions
    www/                          # Marketing landing page
  packages/
    types/                        # Shared TypeScript types
  docs/
    backend/                      # Backend architecture and reference docs
    decisions/                    # Architecture decision records (D-001 through D-052+)
    STATUS.md                     # Current project status and recent completions
    superpowers/                  # Implementation specs, plans, and progress reports
  turbo.json                      # Turborepo pipeline configuration
```

---

## Development Setup

### Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Backend runtime |
| Node.js | 20+ | Frontend runtime |
| uv | Latest | Python package management |
| Supabase CLI | Latest | Local Postgres database (for full local dev) |

### Clone and Configure

```bash
git clone <repo-url>
cd insightxpert.ai
```

### Backend Setup

```bash
cd apps/api

# Install Python dependencies
uv sync

# Copy and configure environment
cp .env.example .env.local
# Edit .env.local with your values (see below)

# Run database migrations
uv run alembic upgrade head

# Start the FastAPI server
uv run uvicorn insightxpert_api.main:app --reload --port 8000
```

**Required environment variables** (in `apps/api/.env.local`):

| Variable | Description |
|---|---|
| `DATABASE_URL` | Supabase Postgres connection string (metadata DB). Use `postgresql+psycopg://...` with pooler (port 6543) for serverless. |
| `SESSION_SECRET` | Secret key for signing session cookies. Generate a random 64-char hex string. |
| `LLM_API_KEY` | API key for the configured LLM provider (Gemini or DeepSeek). |
| `LLM_PROVIDER` | `gemini` or `deepseek`. |
| `LLM_MODEL` | Default model name (e.g., `deepseek-v4-flash`, `gemini-2.5-flash`). |

**Optional variables for specific features:**

| Variable | Description |
|---|---|
| `AUTOMATIONS_ENABLED` | Set to `true` to enable scheduled automations. |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for BYO connection encryption. |
| `GCS_BUCKET` | GCS bucket for uploaded database file storage. |
| `SENTRY_DSN` | Sentry DSN for error monitoring (optional). |
| `LOG_LEVEL` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`). |

### Frontend Setup

```bash
cd apps/web

# Install Node dependencies
npm install

# Start the Next.js dev server
npm run dev
```

The dev server runs on `http://localhost:3000` and proxies `/api/*` to `http://localhost:8000` via Next.js rewrites.

---

## Backend Development

### Module Pattern

Most backend modules follow a consistent 3-layer pattern:

```
feature/
  table.py        -- SQLAlchemy Core table definitions (plain MetaData, no ORM)
  repository.py   -- Thin SQL layer: CRUD using SQLAlchemy Core, returns plain dicts
  service.py      -- Business logic: Pydantic models in/out, validation, scoping
```

Repositories never import Pydantic models. Services never touch SQLAlchemy directly. This separation keeps the data layer swappable and the business logic testable.

### Adding a Route

1. **Table**: Add the table definition in `feature/table.py` using `sqlalchemy.Table`.
2. **Repository**: Add CRUD methods in `feature/repository.py` using `engine.connect()` context managers.
3. **Service**: Add business logic in `feature/service.py` with Pydantic request/response models.
4. **Route**: Create `routes/<feature>.py` as an `APIRouter` with prefix `/api/v1/<feature>`. Import and mount in `routes/__init__.py`.
5. **Migration**: Create an Alembic migration with `uv run alembic revision --autogenerate -m "description"`.

### Adding a Pipeline Stage

Pipeline stages live in `pipeline/`. Each stage implements the `Stage` Protocol:

1. Create `pipeline/<stage_name>_stage.py`.
2. Implement the stage's `run()` method (async generator yielding `ChatChunk` objects).
3. If the stage requires a new chunk type, add it to the `ChunkType` enum in `sse/chunks.py`.
4. If the stage requires a new prompt, create it as a `.j2` file in `vendored/pipeline_core/prompts/`.
5. Wire the stage into the pipeline sequence in `pipeline/` or the orchestrator.

### Adding a Dialect

To support a new database dialect (currently SQLite + Postgres):

1. Create `db/dialects/<dialect>.py` implementing the `DialectAdapter` Protocol (defined in `db/dialects/base.py`).
2. Register the adapter in `db/dialects/__init__.py`.
3. Create `sql_generation_<dialect>.j2` in `vendored/pipeline_core/prompts/`.

The Protocol has 9 methods/properties. Zero changes to existing code are needed for a new dialect.

### Running Tests

```bash
cd apps/api

# Run all tests
uv run pytest tests/ -v

# Run specific test files
uv run pytest tests/test_agent.py -v
uv run pytest tests/test_db_connector_dialect.py -v

# With coverage
uv run pytest tests/ --cov=insightxpert_api --cov-report=term-missing

# Run only tests without LLM dependency (skip gemini-marked tests)
uv run pytest tests/ -v -m "not gemini"
```

### Test Markers

| Marker | Description |
|---|---|
| `gemini` | Tests that require a live LLM API call. Skipped in CI without credentials. |
| `slow` | Long-running tests. Skipped in fast CI runs. |
| `integration` | Tests that require a live database connection. |

### Test Isolation

- Unit tests use an **in-memory SQLite** database created per test session (`conftest.py`).
- Integration tests use a **per-test SQLite file** database, created and destroyed for each test function.
- Tests should never touch the production database.
- The `InMemoryVectorStore` fake is used for RAG-related tests, avoiding the need for pgvector in test environments.

---

## Frontend Development

### App Router Structure

The frontend uses Next.js 15+ App Router with React Server Components:

```
app/
  page.tsx                          # Main chat interface
  layout.tsx                        # Root layout with HealthCheckGate
  login/page.tsx                    # Login form
  automations/
    page.tsx                        # Automations list + new-automation dialog
    layout.tsx                      # AuthGuard wrapper
  databases/
    page.tsx                        # Database browser
    [id]/page.tsx                   # Database detail page
  admin/
    layout.tsx                      # Admin layout with sidebar nav
    overview/page.tsx               # Dashboard with stats and sparklines
    users/page.tsx                  # User management (invite, role, deactivate)
    databases/page.tsx              # Admin database list with visibility controls
    automations/page.tsx            # Admin automations view
    prompts/page.tsx                # Prompt template admin
    rag/page.tsx                    # RAG vector store admin
    conversations/page.tsx          # Cross-user conversation viewer
    metrics/page.tsx                # Query metrics and cost tracking
    audit/page.tsx                  # Audit log viewer
    notifications/page.tsx          # Notification management
  share/[token]/page.tsx            # Shared conversation viewer
  change-password/page.tsx          # Password change form
```

### Zustand Stores

State management uses Zustand with clear session-vs-local persistence boundaries:

| Store | File | Persistence | Purpose |
|---|---|---|---|
| `chat-store` | `stores/chat-store.ts` | sessionStorage | Conversations, active conversation, streaming state, sidebar toggles, selected database |
| `settings-store` | `stores/settings-store.ts` | None | Provider/model selection, agent mode, pipeline mode |
| `client-config-store` | `stores/client-config-store.ts` | None | Feature flags, org branding, admin status |
| `insight-store` | `stores/insight-store.ts` | None | Insights list, unread count, bookmark/delete with optimistic rollback |
| `notification-store` | `stores/notification-store.ts` | None | Notifications list, unread count, mark-read with optimistic rollback |
| `automation-store` | `stores/automation-store.ts` | None | Automation CRUD, test trigger state, trigger templates |

**Convention**: Stores are non-persisted by default. Only `chat-store` persists (to `sessionStorage`, key `"insightxpert-chat"`), and it strips message arrays on save. Messages are lazy-loaded from the server.

### Adding a Chunk Renderer

The SSE pipeline emits typed chunks that the frontend renders with specific components.

1. **Add the chunk type** to `ChunkType` in `types/chat.ts`.
2. **Create the renderer component** in `components/chunks/<name>-chunk.tsx`.
3. **Register it** in `components/chunks/chunk-renderer.tsx` -- add a branch in the dispatcher switch statement.
4. **Add the SSE payload type** in `types/chunks.ts` if the chunk carries structured data.

Example: adding an `answer_generated` chunk type and renderer:

```tsx
// components/chunks/answer-generated-chunk.tsx
export function AnswerGeneratedChunk({ data }: { data: AnswerGeneratedData }) {
  return <div>Answer generated in {data.duration_ms}ms</div>;
}
```

### SSE Client

The SSE client (`lib/sse-client.ts`) manages the streaming HTTP connection:

- `createSSEStream(message, conversationId, callbacks, agentMode, options, token?)` opens a POST to `/api/v1/chat`.
- Returns an `AbortController` for cancellation.
- Reads the `ReadableStream` line-by-line, parsing `data: <json>` SSE lines.
- Uses `queueMicrotask` to batch chunks from the same `reader.read()` batch, exploiting React 18 automatic batching.
- `AgentMode` is `"basic" | "agentic" | "auto"`. `PipelineMode` is `"auto" | "linked" | "full_schema"`.

### Component Patterns

- **API calls**: Use `apiFetch` or `apiCall` from `lib/api.ts`. These attach credentials and base URL automatically.
- **Auth guard**: Pages that require authentication wrap in `AuthGuard` (`components/auth/auth-guard.tsx`).
- **Optimistic updates**: Stores update local state first, then call the API, and roll back on failure.
- **File uploads**: Dialogs follow a consistent pattern: file picker + name input + upload + review/confirm (two-step flow).

---

## Code Quality

### Backend (Python)

| Tool | Configuration | Purpose |
|---|---|---|
| **ruff** | `pyproject.toml` | Linting + import sorting + formatting. Line length: 100. |
| **mypy** | `pyproject.toml` | Static type checking in strict mode. |

Run checks:

```bash
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

### Pre-commit Hooks

The project uses pre-commit to enforce code quality on every commit:

```bash
uv run pre-commit install
uv run pre-commit run --all-files  # Run manually
```

### Frontend (TypeScript)

| Tool | Configuration | Purpose |
|---|---|---|
| **ESLint** | `eslint.config.mjs` with `eslint-config-next` | Linting |
| **TypeScript** | `tsconfig.json` (strict mode) | Type checking |

Run checks:

```bash
cd apps/web
npm run lint
npx tsc --noEmit
```

---

## Decision Records

Architecture decisions are documented as decision records in `docs/decisions/`. Each record follows a consistent template.

### Adding a New Decision

1. Copy `docs/decisions/.template.md` to `docs/decisions/D-NNN-short-title.md` (use the next available number).
2. Fill in all sections: Context, Decision, Alternatives Considered, Consequences.
3. Add the **code marker** in the affected source files (a comment referencing the decision number).
4. Regenerate the index by running the index script (if one exists) or manually updating any index files.
5. Set `Status` to `decided`. Use `proposed` for decisions still under discussion.

### Decision Categories

| Prefix | Category |
|---|---|
| D-001 to D-019 | Architecture: runtime, hosting, vendoring |
| D-020 to D-029 | API design: routes, payloads, error shapes |
| D-030 to D-039 | Patterns: Protocols, caches, threading |
| D-040 to D-049 | Infrastructure: hosting, storage, pooling |
| D-050 to D-059 | Security: auth, hashing, encryption |

---

## Testing Strategy

### Backend Tests

| Type | What they test | Marker | Count |
|---|---|---|---|
| **Unit** | Individual functions/modules: hashing, SQL validation, trigger evaluation | (none) | ~180 |
| **Integration** | HTTP endpoints with in-memory SQLite: chat, databases, auth, admin | (none) | ~80 |
| **LLM-dependent** | End-to-end pipeline with real LLM calls | `@pytest.mark.gemini` | ~20 |

Run subsets:

```bash
uv run pytest tests/ -v                          # All tests (unit + integration, no LLM)
uv run pytest tests/ -v -m "not gemini"          # Skip LLM-dependent tests
uv run pytest tests/ -v -m "gemini"              # Only LLM-dependent tests
uv run pytest tests/test_db_connector_dialect.py -v  # Dialect-specific tests
```

### Frontend Tests

```bash
cd apps/web
npm run test              # Vitest unit tests (components, stores, utilities)
npm run test:e2e          # Playwright end-to-end tests (headless)
npm run test:e2e:ui       # Playwright with UI browser
```

---

## Pull Request Process

### Branch Naming

Follow the convention: `<type>/<short-description>`

| Type | Use for |
|---|---|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code restructuring without behavior change |
| `perf/` | Performance improvements |
| `chore/` | Maintenance tasks, dependency updates |

Examples: `feat/add-bigquery-dialect`, `fix/automation-duplicate-tick`, `perf/chat-preflight-parallel`.

### PR Checklist

Before opening a pull request:

1. **Tests pass**: `uv run pytest tests/ -v -m "not gemini"` all green.
2. **Lint passes**: `uv run ruff check .` and `npm run lint` clean.
3. **Type checks pass**: `uv run mypy src/` and `npx tsc --noEmit` clean.
4. **New decisions**: If your change introduces an architectural choice, add a decision record.
5. **Migration**: If your change modifies the database schema, include an Alembic migration.
6. **Chunk types**: If your change adds SSE chunk types, register them in both `sse/chunks.py` and `types/chat.ts`.
7. **PR template**: Fill in the description with what, why, and how to test.
8. **Decision records affected**: List any decisions your PR touches, supersedes, or creates.

### CI Checks

The CI pipeline runs on every PR:

1. Backend: ruff, mypy, pytest (no LLM markers)
2. Frontend: ESLint, TypeScript, Vitest
3. Build: Verify both apps build without errors

---

## Project Conventions

### Backend

- All agent loops are `async def` functions that yield `ChatChunk` objects via `AsyncGenerator`.
- All synchronous DB calls in `async def` handlers must be wrapped in `await asyncio.to_thread(...)`. SQLAlchemy Core is synchronous; calling it directly blocks the event loop.
- Error messages returned to the LLM must not include Python tracebacks.
- New feature toggles go in the client-config route and must be surfaced in the admin UI.
- New services follow the repository/service split pattern: accept an SQLAlchemy `engine` in `__init__`, use context managers, return plain dicts.
- All new SQLAlchemy tables use `_uuid()` for primary keys and `_utcnow()` for timestamps.
- New API routers mount at `/api/v1/<module>` and are registered in `main.py`.
- Synchronous storage services (GCS, local FS) must be called via `asyncio.to_thread()`.

### Frontend

- New chunk types must be added to `ChunkType` in `types/chat.ts` and handled in `components/chunks/chunk-renderer.tsx`.
- New stores should be non-persisted by default. Use `sessionStorage` for session state, `localStorage` for true persistence.
- All API calls go through `apiFetch` or `apiCall` in `lib/api.ts`.
- New page routes follow Next.js App Router convention (directory with `page.tsx`).
- New TypeScript types go in `types/` -- one file per domain.
- Prefer `useCallback` for event handlers passed to children.
- `React.memo` is used on expensive renderers (`AnswerChunk`, `InsightChunk`) to avoid re-parsing markdown on unrelated state updates.
