# Design Patterns in InsightXpert.ai

A catalog of the key design patterns that define the architecture. Each pattern covers what it is, where it lives, why it is used, and what tradeoffs it makes.

---

## Table of Contents

1. [Stage Protocol](#1-stage-protocol)
2. [DialectAdapter Pattern](#2-dialectadapter-pattern)
3. [Repository/Service Split](#3-repositoryservice-split)
4. [LLM Factory Pattern](#4-llm-factory-pattern)
5. [Protocol-Based Adapters](#5-protocol-based-adapters)
6. [Two-Engine Pool Architecture](#6-two-engine-pool-architecture)
7. [SSE Chunk Taxonomy](#7-sse-chunk-taxonomy)
8. [Async Batching Queue](#8-async-batching-queue)
9. [Error-as-Flag Pipeline](#9-error-as-flag-pipeline)
10. [In-Process Caching with TTL](#10-in-process-caching-with-ttl)
11. [Preflight Parallelism](#11-preflight-parallelism)
12. [Fire-and-Forget Persistence](#12-fire-and-forget-persistence)

---

## 1. Stage Protocol

**Docs:** `docs/decisions/D-004-stage-protocol.md`

### Pattern

The pipeline is composed of stages that conform to a structural protocol:

```python
class ProfilerStage:
    name: str = "profiler"

    async def run(self, ctx: PipelineContext, current: Any) -> Any:
        ...
```

Each stage:
- Has a `name` class attribute (used in SSE `STATUS` chunks and logging).
- Implements `async def run(ctx, current) -> Any` where `current` is the previous stage's return value.
- Reads from and writes to a shared `PipelineContext` (a dict-like object on `ctx.state`).
- Emits SSE chunks via `ctx.emit(chunk_type, payload)`.
- Either returns a value (passed to the next stage as `current`) or sets `ctx.state["error"]` to signal failure.

### Why Structural Subtyping

Stages are not forced to inherit from a base class. The `Pipeline.run_scalar()` method simply iterates over a list of objects and calls `.run(ctx, current)` on each. This is structural subtyping (duck typing) rather than nominal subtyping (ABC inheritance).

**Advantages:**
- Stages can be written without importing any base class.
- No fragile base class problem -- stages are fully self-contained.
- Easy to mock/test: any object with `name` and `async def run(...)` works.

### Pipeline Construction

Stages are assembled in `pipeline/__init__.py`:

```python
def default_pipeline() -> Pipeline:
    return Pipeline([
        ProfilerStage(),
        SchemaLinkerStage(),  # or FullSchemaStage()
        SqlGeneratorStage(),
        SqlValidatorStage(),
        SqlExecutorStage(),
        SqlRefinerStage(),
        AnswerSynthesizerStage(),
    ])
```

The second stage is selected at construction time based on `pipeline_mode`: `"linked"` -> `SchemaLinkerStage`, `"full_schema"` -> `FullSchemaStage`.

### Tradeoffs

- **Pro**: No inheritance hierarchy to refactor when adding stages.
- **Pro**: Stages can be mixed and matched, swapped, or reordered freely.
- **Con**: No compile-time check that a stage implements `run()` -- though this is caught immediately at first invocation.

---

## 2. DialectAdapter Pattern

**Docs:** `docs/decisions/D-006-dialect-adapter-strategy.md`

### Pattern

SQL generation, execution, and validation vary by database engine (SQLite vs PostgreSQL). The `DialectAdapter` pattern encapsulates these differences behind a common protocol:

```python
class DialectAdapter(Protocol):
    dialect_name: str

    def validate_sql(self, sql: str) -> bool: ...
    def get_tables_query(self) -> str: ...
    def get_schema_query(self, table: str) -> str: ...
    def format_limit(self, sql: str, limit: int) -> str: ...
    def pragma_for_read_only(self) -> str | None: ...
```

### Registry

Dialects are registered in a mapping:

```python
_DIALECT_REGISTRY: dict[str, DialectAdapter] = {
    "sqlite": SQLiteAdapter(),
    "postgres": PostgresAdapter(),
}
```

### One File Per Dialect

Each dialect has its own module with a single adapter class:
- `dialects/sqlite.py` -- `SQLiteAdapter`
- `dialects/postgres.py` -- `PostgresAdapter`

### Call-Site Usage

```python
adapter = get_adapter(db_kind)  # looks up in registry
sql = adapter.format_limit(sql, row_limit)
is_valid = adapter.validate_sql(sql)
```

Adding a new dialect (e.g., MySQL) requires: one new file with an adapter class + one registry entry. No call-site code changes.

### Tradeoffs

- **Pro**: All dialect-specific logic is co-located in one file per dialect.
- **Pro**: Zero call-site churn when adding a new dialect.
- **Pro**: Protocol-based: adapters don't inherit from a base class.
- **Con**: Protocol methods must be manually kept in sync across dialects (structural, no compiler enforcement).

---

## 3. Repository/Service Split

**Docs:** `docs/decisions/D-030-repository-service-split.md`

### Pattern

Every domain module separates data access (repository) from business logic (service):

```
table.py       # SQLAlchemy Table definition (metadata)
repository.py  # Raw SQL operations (returns plain dicts)
service.py     # Business logic (uses Pydantic models)
```

### Example: Users Module

```
users/table.py      # users table: columns, constraints, indices
users/repository.py # insert_user, get_by_id, get_by_email, list_users, update_user, delete_user
users/service.py    # invite, authenticate, change_password, set_role, set_active, delete
```

### Rules

1. **Repositories** never import Pydantic models. They accept and return plain Python dicts/tuples.
2. **Services** never touch SQLAlchemy directly. They call repository methods.
3. **Tables** only define the SQL schema, no behavior.

### Why

- **Testability**: Services can be tested with a mock repository; repositories can be tested against a real database.
- **Cohesion**: Business rules (LastAdminError, email lowercasing, session invalidation on password change) live in one place.
- **No leaky ORM**: Pydantic DTOs don't depend on SQLAlchemy.

### Tradeoffs

- **Pro**: Clear separation of concerns. Services are framework-agnostic.
- **Pro**: Easy to add a new query method without touching business logic.
- **Con**: More files per domain (3 instead of 1). Accepted tradeoff for maintainability.

---

## 4. LLM Factory Pattern

**Docs:** `docs/decisions/D-007-provider-agnostic-llm-factory.md`

### Pattern

A single factory function creates the appropriate LLM provider without call-site knowledge of which provider is in use:

```python
def create_chat_llm(settings: Settings) -> ChatLLM:
    provider = settings.llm_provider  # "gemini" or "deepseek"
    if provider == "gemini":
        return GeminiLLM(api_key=settings.gemini_api_key, model=settings.gemini_chat_model)
    if provider == "deepseek":
        return DeepSeekLLM(api_key=settings.deepseek_api_key, model=settings.deepseek_chat_model)
```

### Provider-Neutral Interface

All providers implement a shared interface:

```python
class ChatLLM(Protocol):
    model: str

    async def async_generate(self, prompt: str) -> str: ...
    async def async_generate_stream(self, prompt: str) -> AsyncGenerator[str, None]: ...
    async def async_embed(self, text: str) -> list[float]: ...

    @property
    def input_tokens_used(self) -> int: ...
    @property
    def output_tokens_used(self) -> int: ...
```

### Token Tracking

A single `ChatLLM` instance is created per chat turn and shared across all pipeline stages. Its `input_tokens_used` / `output_tokens_used` accumulators are incremented by every LLM call. The route layer reads them once at the end for the terminal `metrics` chunk.

### Cost Attribution

LLM usage is tracked via `record_llm_usage()` with versioned pricing:

```python
# metrics/pricing.py
PRICING = {
    "gemini-2.5-flash": ModelPricing(input_per_1m=0.30, output_per_1m=2.50),
    "deepseek-v4-flash": ModelPricing(input_per_1m=0.14, output_per_1m=0.28),
}
```

Every `query_metrics` row stamps `pricing_version` and `cost_usd`.

### Tradeoffs

- **Pro**: Switching providers is an env var change (`LLM_PROVIDER=deepseek`).
- **Pro**: Adding a new provider is one new module + one factory branch.
- **Pro**: Token tracking is transparent to pipeline code -- the shared instance accumulates automatically.
- **Con**: The factory uses conditional branches, not a registry. For 2-3 providers this is fine.

---

## 5. Protocol-Based Adapters

**Docs:** `docs/decisions/D-031-protocol-based-adapters.md`

### Pattern

Throughout the codebase, adapters and abstractions use Python Protocols (structural subtyping) rather than abstract base classes:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ObjectStore(Protocol):
    async def put_bytes(self, key: str, data: bytes) -> None: ...
    async def get_bytes(self, key: str) -> bytes | None: ...
    def exists(self, key: str) -> bool: ...
    async def list(self, prefix: str) -> list[str]: ...
    async def delete(self, key: str) -> None: ...
```

### Implementations

| Protocol | Implementations |
|---|---|
| `ObjectStore` | `LocalStorage` (filesystem), `GCSStorage` (Google Cloud Storage) |
| `ChatLLM` | `GeminiLLM`, `DeepSeekLLM` |
| `DialectAdapter` | `SQLiteAdapter`, `PostgresAdapter` |

### Factory Selection

```python
def build_store(settings: Settings) -> ObjectStore:
    return GCSStorage(settings.gcs_bucket) if settings.gcs_bucket else LocalStorage(settings.local_storage_dir)
```

### Why Protocols Over ABCs

- **No inheritance required**: Third-party code can satisfy the protocol without our base class.
- **`@runtime_checkable`**: `isinstance(obj, ObjectStore)` works for structural checking.
- **Lighter weight**: No metaclass conflicts, no `__init_subclass__` hooks.

### Tradeoffs

- **Pro**: Maximum flexibility -- any object with the right methods works.
- **Pro**: No dependency on a shared base class module.
- **Con**: No default method implementations (ABCs can provide those).
- **Con**: Method signature mismatches are runtime errors, not type-checker errors (unless using mypy/pyright with protocol checking).

---

## 6. Two-Engine Pool Architecture

**Docs:** `docs/decisions/D-060-two-engine-pool-architecture.md`

### Pattern

The metadata database has two independent SQLAlchemy engine singletons:

| Engine | Pool Size | Overflow | Timeout | Used By |
|---|---|---|---|---|
| Request | 15 | 10 | 10s | All HTTP route handlers |
| Background | 2 | 0 | 30s | Automation scheduler/runner |

### Why Two Pools

Without isolation, a burst of automation runs could exhaust all connections in the shared pool, starving user-facing requests. The two-pool design guarantees that user requests always have connections available, and background work is capped at 2 connections.

### Lazy Initialization

```python
# db/engine.py
_request_engine: Engine | None = None

def get_request_engine() -> Engine:
    global _request_engine
    if _request_engine is None:
        _request_engine = _create_engine(pool_size=15, max_overflow=10, pool_timeout=10)
    return _request_engine
```

Engines are created on first access, not at import time.

### Test Hook

```python
def reset_engine_cache() -> None:
    """Dispose and clear both engine singletons. Used by tests between runs."""
```

### Pgbouncer Compatibility

For Postgres with pgbouncer transaction pooling:
- `pool_pre_ping = False` (pgbouncer handles connection health).
- `prepare_threshold = None` via psycopg3 `connect_args` (prepared statements are incompatible with transaction pooling).
- Alembic migrations use a separate direct (non-pooler) URL.

### Tradeoffs

- **Pro**: Request-serving and background work are fully isolated.
- **Pro**: Background pool sizing is independent of request pool.
- **Con**: Two pools = two sets of connections = higher total connection count.
- **Con**: With pgbouncer, the isolation is partially redundant (pgbouncer already pools).

---

## 7. SSE Chunk Taxonomy

**Docs:** `docs/decisions/D-005-sse-streaming-chunk-taxonomy.md`, `docs/decisions/D-022-sse-envelope-shape.md`

### Pattern

Every event sent over the SSE connection uses a typed envelope:

```json
{
    "type": "sql_generated",
    "data": {"sql": "SELECT ...", "iteration": 0},
    "conversation_id": "abc123...",
    "timestamp": 1711910400.123
}
```

### Chunk Types (Closed Set)

The `ChunkType` enum defines every valid type:

**Pipeline progress:**
| Type | Emitted By | Payload |
|---|---|---|
| `status` | Pipeline runner | `{label: str}` |
| `profile_loaded` | ProfilerStage | `{db_id, table_count, column_count, from_cache}` |
| `schema_linking_started` | SchemaLinkerStage | `{}` |
| `candidate_sqls_generated` | SchemaLinkerStage | `{candidates: [...]}` |
| `literals_extracted` | SchemaLinkerStage | `{literals: [...]}` |
| `semantic_matches` | SchemaLinkerStage | `{columns: [...]}` |
| `join_paths_added` | SchemaLinkerStage | `{paths: [...]}` |
| `linked_schema_final` | SchemaLinkerStage | `{schema_text: str}` |
| `sql_generated` | SqlGeneratorStage | `{sql: str, iteration: int}` |
| `sql_executing` | SqlExecutorStage | `{}` |
| `rows_returned` | SqlExecutorStage | `{columns, rows, row_count, execution_time_ms}` |
| `answer_delta` | AnswerSynthesizerStage | `{text: str}` (incremental) |
| `answer_generated` | Route epilogue | `{answer: str}` (canonical full text) |

**Orchestrator-specific:**
| Type | Emitted By | Payload |
|---|---|---|
| `tool_call` | Analyst adapter | `{tool_name: str}` |
| `tool_result` | Analyst adapter | `{tool_name, data}` |
| `orchestrator_plan` | Orchestrator | `{tasks: [...]}` |
| `enrichment_trace` | DAG executor | `{task_id, status, result}` |
| `insight` | Synthesizer | `{title, content, categories, citations}` |

**Terminal:**
| Type | Emitted By | Payload |
|---|---|---|
| `metrics` | Route epilogue | `{latency_ms, prompt_tokens, output_tokens, total_tokens, model}` |
| `error` | Any stage on failure | `{code: str, message: str}` |

### Frontend Dispatch

The `ChunkRenderer` component maps each `type` to a dedicated React component:

```
type="status"           -> StatusChunk
type="sql_generated"     -> SqlChunk
type="rows_returned"    -> ToolResultChunk
type="answer_delta"     -> AnswerChunk
type="tool_call"        -> ToolCallChunk
type="error"            -> ErrorChunk
type="insight"          -> InsightChunk
...
```

### Tradeoffs

- **Pro**: Strongly typed -- each chunk type has a specific Pydantic model for its `data` field.
- **Pro**: FE dispatch is a simple switch on `type` -- adding a new chunk type adds one case + one component.
- **Pro**: Human-readable JSON enables debugging via browser devtools EventStream tab.
- **Con**: The closed enum means new chunk types require both backend and frontend changes.
- **Con**: JSON serialization overhead per chunk. Acceptable given typical chunk counts (< 100 per request).

---

## 8. Async Batching Queue

**Docs:** `docs/decisions/D-073-audit-backpressure.md`

### Pattern

The audit system uses an async queue with batched writes and back-pressure:

```python
# audit/queue.py
_queue: asyncio.Queue[AuditRow] = asyncio.Queue(maxsize=5000)
```

### Producer (Middleware)

For every non-GET HTTP request, `AuditMiddleware` enqueues an `AuditRow`. The enqueue is non-blocking (fire-and-forget). If the queue is full, the oldest entry is dropped, and a warning is logged (rate-limited to once per 30s).

### Consumer (Background Task)

A background `asyncio.Task` drains the queue in batches:

- **Batch size**: 50 rows per DB insert.
- **Batch interval**: 200ms between flushes.
- **DB write**: Wrapped in `asyncio.to_thread` so it does not block the event loop.

```python
async def _drain_loop():
    while True:
        batch = []
        try:
            batch.append(await asyncio.wait_for(_queue.get(), timeout=0.2))
            # Collect up to 50 more without blocking
            while len(batch) < 50:
                try:
                    batch.append(_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
        except asyncio.TimeoutError:
            pass  # No new entries in 200ms, flush whatever we have

        if batch:
            await asyncio.to_thread(_insert_batch, batch)
```

### Shutdown

On server shutdown, the queue's `stop()` method:
1. Cancels the drain loop.
2. Drains remaining entries from the queue.
3. Flushes the final batch.

### Guarantees

- **Best-effort**: No delivery guarantee. Entries can be lost (queue overflow, crash before flush).
- **Zero latency impact**: Middleware never blocks on audit I/O.
- **Bounded memory**: Queue size cap prevents unbounded growth.

### Tradeoffs

- **Pro**: Audit logging adds zero latency to user requests.
- **Pro**: Batching reduces DB write pressure (1 insert per 50 events).
- **Con**: Eventual loss in crash scenarios -- audit is not a system of record.
- **Con**: Oldest-drop on overflow means the most recent events are dropped, which may be more valuable during a burst.

---

## 9. Error-as-Flag Pipeline

### Pattern

Pipeline stages do not raise exceptions for recoverable errors. Instead, they write an error sentinel to `ctx.state["error"]`:

```python
# SqlValidatorStage
try:
    sqlglot.parse_one(sql, dialect="sqlite")
except Exception as e:
    ctx.state["error"] = f"sql_validation_failed: {e}"
    ctx.emit("error", {"code": "sql_validation_failed", "message": str(e)})
    return None
```

### Recovery Chain

```
SqlValidatorStage: sqlglot parse fails -> ctx.state["error"] = "..."
SqlExecutorStage: sees "error" already set -> skips execution
SqlRefinerStage:   sees "error" -> enters retry loop (up to 2 iterations)
                   recovers -> clears ctx.state["error"] = None
                   cannot recover -> leaves error set
SynthesizerStage:  sees "error" -> skips entirely (returns "")
```

### Why Not Exceptions

Exceptions abort the pipeline entirely. The error-as-flag approach allows downstream stages (specifically the refiner) to attempt recovery. If the refiner succeeds, the answer is still delivered. The user never sees a "pipeline failed" error unless all recovery attempts are exhausted.

### Tradeoffs

- **Pro**: Graceful degradation -- temporary errors are recoverable.
- **Pro**: No try/except chains in the pipeline runner.
- **Con**: Stages must check `ctx.state["error"]` at the beginning of `run()`. Easy to forget.
- **Con**: Error state is implicit -- you cannot tell from a stage's signature whether it can handle errors.

---

## 10. In-Process Caching with TTL

**Docs:** `docs/decisions/D-065-in-process-caches-30s-ttl.md`

### Pattern

Multiple subsystems use in-process dict caches with short TTLs:

| Cache | TTL | Purpose |
|---|---|---|
| User auth cache | 30s | Avoid DB lookup on every request |
| Profile cache | Process lifetime + LRU | Avoid repeated profiling |
| Admin overview cache | 30s | Avoid aggregate queries on admin page load |
| Settings singleton | Process lifetime | Read once from env |

### Profile Cache (Singleflight)

The profiling cache uses per-key `asyncio.Lock` to prevent concurrent profiling of the same database:

```python
class ProfileCache:
    _cache: dict[str, tuple[DatabaseProfile, float]]  # (profile, timestamp)
    _locks: dict[str, asyncio.Lock]                    # per-key lock

    async def aget(self, db_id: str) -> DatabaseProfile | None:
        if db_id not in self._locks:
            self._locks[db_id] = asyncio.Lock()

        async with self._locks[db_id]:
            # Check again inside lock (may have been populated by another waiter)
            if db_id in self._cache:
                return self._cache[db_id]

            # Load from DB, populate cache
            ...
```

### Why 30s TTL

Short enough that config changes propagate quickly, long enough to eliminate 99%+ of redundant DB reads for hot paths (auth, admin overview).

### Tradeoffs

- **Pro**: Drastically reduces DB load for read-heavy paths.
- **Pro**: No external cache dependency (Redis, Memcached).
- **Con**: Stale reads for up to TTL duration.
- **Con**: Lost on instance recycle (acceptable for Cloud Run with min-instances=1).
- **Con**: No cross-instance invalidation -- config changes take up to TTL on other instances.

---

## 11. Preflight Parallelism

### Pattern

Before the pipeline runs, three independent operations execute concurrently via `asyncio.TaskGroup`:

```python
async def _preflight_concurrent(...):
    async with asyncio.TaskGroup() as tg:
        tg.create_task(prefetch_profile(ctx, db_id))
        tg.create_task(classify_mode(ctx, llm, question))
        tg.create_task(prefetch_few_shot_example(ctx, llm, question, db_id))
```

### Operations

| Operation | I/O Type | Purpose |
|---|---|---|
| Profile prefetch | DB read | Load cached `DatabaseProfile` (or None) |
| Mode classification | LLM call | Classify as "basic" or "agentic" (only when `agent_mode="auto"`) |
| Few-shot retrieval | Embedding + vector search | Find similar BIRD-train QA pair |

### Isolation

Each task has its own try/except -- failure in one never cancels the others. Profile prefetch fails -> returns None (ProfilerStage handles cold-cache). Mode classification fails -> defaults to "agentic" (bias toward correctness). Few-shot fails -> returns None (prompt renders without {few_shot_example} block).

### Tradeoffs

- **Pro**: Cuts steady-state latency by up to 2 sequential round-trips.
- **Pro**: Graceful degradation on any single failure.
- **Con**: TaskGroup requires Python 3.11+. Any child failure cancels all siblings by default -- requires individual try/except for isolation.

---

## 12. Fire-and-Forget Persistence

### Pattern

After the SSE stream sends `[DONE]`, persistence runs as a background task:

```python
# In route handler, after emitter.stream() completes
asyncio.ensure_future(
    asyncio.to_thread(_record_conversation_snapshot, user_id, conversation_id, messages, chunks)
)
asyncio.ensure_future(
    asyncio.to_thread(_record_turn, user_id, conversation_id, db_id, question, sql, metrics)
)
```

### Why

Persisting large responses (with chunk blobs containing full result rows) to Postgres can take seconds. Without fire-and-forget, the client would wait for persistence to complete before seeing `[DONE]` -- a significant latency gap the user perceives.

### Guarantees

- **Best-effort**: If persistence fails (e.g., DB connection lost), the conversation is still in the in-memory store. The next request can hydrate from memory.
- **Logged**: Persistence failures are logged at warning level with context.
- **Non-blocking**: The route handler returns `EventSourceResponse` immediately after the first chunk.

### Tradeoffs

- **Pro**: User-perceived latency matches LLM generation time, not LLM + persistence time.
- **Pro**: Persistence failures do not degrade the chat experience.
- **Con**: Possible data loss if the instance recycles between `[DONE]` and persistence completing.
- **Con**: No mechanism to notify the client if persistence fails -- the conversation just won't appear in history after a reload.

---

## Summary

| Pattern | What It Solves | Key Files |
|---|---|---|
| Stage Protocol | Swappable, composable pipeline stages | `pipeline/profiler_stage.py`, `pipeline/linker_stage.py`, etc. |
| DialectAdapter | Multi-dialect SQL without call-site churn | `pipeline/dialects/sqlite.py`, `pipeline/dialects/postgres.py` |
| Repository/Service Split | Separates data access from business logic | `users/table.py`, `users/repository.py`, `users/service.py` |
| LLM Factory | Provider-agnostic LLM access | `llm/gemini.py`, `llm/deepseek.py`, `llm/factory.py` |
| Protocol-Based Adapters | Structural subtyping over inheritance | `storage/`, `llm/`, `pipeline/dialects/` |
| Two-Engine Pool | Isolates request-serving from background work | `db/engine.py` |
| SSE Chunk Taxonomy | Typed streaming events for FE dispatch | `sse/chunks.py`, `sse/emitter.py` |
| Async Batching Queue | Zero-latency audit logging | `audit/queue.py`, `audit/middleware.py` |
| Error-as-Flag Pipeline | Recoverable pipeline errors | `pipeline/refiner_stage.py` |
| In-Process Caching | Eliminates redundant DB reads | `profiling/cache.py`, `auth/current_user.py` |
| Preflight Parallelism | Concurrent pre-pipeline operations | `routes/chat.py` (`_preflight_concurrent`) |
| Fire-and-Forget Persistence | Decouples user latency from DB writes | `routes/chat.py` (post-SSE persistence) |

For the complete set of architecture decisions with rationale and tradeoffs, see `docs/decisions/` (55+ records).
