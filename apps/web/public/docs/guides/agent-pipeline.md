# InsightXpert.ai Pipeline & SSE Streaming

InsightXpert.ai converts natural-language questions into SQL queries through a multi-stage pipeline. Every stage is transparent -- the frontend sees schema linking, candidate SQLs, row counts, and answer synthesis as they happen via SSE streaming. This document covers the pipeline architecture, every stage in detail, and the SSE chunk taxonomy that enables full transparency.

---

## 1. Pipeline Overview

The text-to-SQL pipeline consists of **8 stages** that run sequentially, each implementing the `Stage` Protocol. The pipeline is constructed in `pipeline/__init__.py`:

```
ProfilerStage
  → SchemaLinkerStage | FullSchemaStage  (depends on pipeline_mode)
    → SqlGeneratorStage
      → SqlValidatorStage
        → SqlExecutorStage
          → SqlRefinerStage
            → AnswerSynthesizerStage
```

Flow:
1. **Profiler** extracts schema, collects stats, builds join graph and vector index.
2. **SchemaLinker** (or FullSchemaStage) selects relevant tables/columns for the question.
3. **SqlGenerator** produces candidate SQL via LLM.
4. **SqlValidator** checks SQL syntax with sqlglot.
5. **SqlExecutor** runs the SQL against the user's database.
6. **SqlRefiner** retries on execution errors (up to 2 iterations).
7. **Synthesizer** streams the final answer with `[^N]` footnotes.

Each stage emits typed SSE chunks so the user sees exactly what is happening. No stage is silent.

---

## 2. Stage Protocol

Every pipeline stage implements the `Stage` Protocol (PEP 544 structural typing):

```python
@runtime_checkable
class Stage(Protocol):
    name: str
    async def run(self, ctx: PipelineContext, input: Any) -> Any: ...
```

### PipelineContext

The shared context threaded through all stages:

```python
@dataclass
class PipelineContext:
    session_id: str
    conversation_id: str
    emitter: EventEmitter | None = None
    state: dict[str, Any] = field(default_factory=dict)
```

Key design choices:
- **`typing.Protocol`** (not `abc.ABC`): Structural subtyping means any object with `name` and `run()` satisfies the contract. Vendored pipeline classes don't need to inherit from our base class.
- **`@runtime_checkable`**: Enables `isinstance(obj, Stage)` checks at registration time.
- **`ctx.state` is a plain `dict[str, Any]`**: Stages read/write different keys (`question`, `db_id`, `profile`, `schema_text`, `sql`, `rows`, `answer`). A typed model would force all stages to know about all possible keys.
- **`ctx.emitter`**: Optional `EventEmitter` for SSE transparency. Set once at pipeline construction and shared across all stages.

### Pipeline Runner

`Pipeline.run_scalar()` iterates stages sequentially. For each stage:
1. Logs `stage.start`.
2. Emits `STATUS` chunk with stage name.
3. Calls `await stage.run(ctx, current)` -- `current` is the previous stage's return value.
4. Logs `stage.end` with elapsed ms.
5. On exception: logs `stage.error`, emits `ERROR`, **re-raises** (aborting pipeline).

### Input/Output Contract

Each stage declares what it reads from `ctx.state` and what it writes and returns:

| Stage | Reads from ctx.state | Returns | Writes to ctx.state |
|---|---|---|---|
| ProfilerStage | `db_id`, `__prefetched_profile` | `DatabaseProfile` | `profile` |
| SchemaLinkerStage | `question`, `profile`, `db_id` | `{schema_text, ...}` | `schema_text`, `column_sources`, `linked_tables`, `linked_columns` |
| SqlGeneratorStage | `question`, `schema_text`, `few_shot_example` | SQL string | `sql` |
| SqlValidatorStage | `sql` | SQL string | `error` (on failure) |
| SqlExecutorStage | `sql`, `db_id`, `error` (skip flag) | rows list | `rows` or `error` |
| SqlRefinerStage | `error`, `sql`, `schema_text`, `question` | refined SQL | `rows` or `error` |
| AnswerSynthesizerStage | `question`, `schema_text`, `sql`, `rows` | answer string | `answer` |

### Error-as-Flag Pattern

The validator and executor do **not raise exceptions**. They write `ctx.state["error"]` as a sentinel string:

```
SqlValidatorStage: sqlglot parse fails → ctx.state["error"] = "sql_validation_failed: ..."
SqlExecutorStage: sees "error" already set → skips execution
                  execution fails → ctx.state["error"] = "sql_execution_error: ..."
SqlRefinerStage:   sees "error" → enters retry loop
                   recovers → clears ctx.state["error"]
                   can't recover → leaves ctx.state["error"] set
SynthesizerStage:  sees "error" → skips entirely (returns "")
```

This allows the refiner to recover from validation/execution errors without aborting the entire pipeline.

---

## 3. Stage-by-Stage Detail

### Stage 1: ProfilerStage (`name="profiler"`)

**File:** `pipeline/profiler_stage.py`

The profiler extracts and caches everything needed about the database schema.

**Process:**
1. Pops `__prefetched_profile` from context (populated during preflight). If present, uses immediately (skips DB read).
2. Else: checks `ProfileService.load()` (Postgres metadata DB → in-process cache).
3. Else: runs the full `build_profile()` flow:
   - Opens the database file via `vendored.pipeline_core.db.SQLiteDatabase`.
   - Extracts schema via `SchemaExtractor.extract()`.
   - Collects column stats via `StatsCollector.collect()`.
   - Auto-disables LLM stages if total columns > `PROFILING_MAX_COLUMNS_FOR_LLM` (default 500).
   - Runs batched LLM summary + quirk generation (from the `profiling/` module).
4. Saves via `ProfileService.save()` (upserts to Postgres, invalidates in-process cache).
5. Resolves DB file path.

**Batching**: LLM calls are batched (20 columns per call, configurable via `PROFILING_BATCH_SIZE`) instead of one call per column. A `batch_disabled` escape hatch exists for per-column mode.

**Cost gating**: Before LLM profiling begins, a cost estimate is computed and the system emits a `profile_cost_estimate` chunk. If the cost exceeds a threshold, profiling requires user confirmation (the "cost gate handshake").

**Quirk detection**: Rule-based heuristics detect special characters in values, numbered groups, FK aliases, type mismatches, symbolic values, and enum labels. Detected quirks are enriched with LLM-generated semantic hints.

**Vector index**: Column descriptions are embedded and indexed for cosine-similarity semantic search used by SchemaLinkerStage.

**LSH index**: MinHash-based Locality-Sensitive Hashing index for literal value matching (used by SchemaLinkerStage).

**Join graph**: `JoinGraphBuilder` builds a graph from declared foreign keys + implicit edges (column-name matching with SQL containment verification).

**Emits**: `PROFILE_LOADED` with `{db_id, table_count, column_count, from_cache}`

### Stage 2a: SchemaLinkerStage (`name="schema_linker"`)

**File:** `pipeline/linker_stage.py`

The linker selects which tables and columns are relevant to the user's question. This is the most complex stage, with 5 signal sources:

**1. Trial SQL Generation**
- Renders `single_prompt_linking_clean.j2` with the full schema.
- Calls LLM to generate candidate SQL queries.
- Parses fenced SQL blocks via regex.
- Extracts table/column references from each candidate.
- Deduplicates across candidates via `union_fields()`.
- **Emits**: `CANDIDATE_SQLS_GENERATED`

**2. LSH Literal Matching** (best-effort)
- Loads the pickled LSH index if available.
- Matches SQL string literals to actual column values.
- Finds columns whose values contain the literals referenced in candidate SQLs.
- **Emits**: `LITERALS_EXTRACTED`

**3. Vector Semantic Search** (best-effort)
- Loads the `VectorIndex` if available.
- Embeds the user's question.
- Searches top-10 columns with cosine similarity > 0.5.
- **Emits**: `SEMANTIC_MATCHES`

**4. FK Join Paths**
- `add_join_paths()` expands the linked set by following declared foreign keys.
- Connects tables that are reachable through FK relationships.
- **Emits**: `JOIN_PATHS_ADDED`

**5. Bridge FK Discovery**
- Detects implicit foreign keys not declared in the schema.
- Uses column-name heuristics (e.g., `table_id` patterns).

**6. Quirk Consumption**
- Reads `ColumnQuirks` from the profile (FK aliases, enum labels, semantic hints).
- Uses quirk information to improve column selection accuracy.

**7. Final Render**
- Renders the linked schema as a compact text block for SQL generation.
- **Emits**: `LINKED_SCHEMA_FINAL`

**Emits sequence**: `SCHEMA_LINKING_STARTED` → `CANDIDATE_SQLS_GENERATED` → `LITERALS_EXTRACTED` → `SEMANTIC_MATCHES` → `JOIN_PATHS_ADDED` → `LINKED_SCHEMA_FINAL`

### Stage 2b: FullSchemaStage (`name="full_schema"`)

**File:** `pipeline/full_schema_stage.py`

A complete bypass of the linker. Re-extracts the schema from the database file via `SchemaExtractor.extract()` (the profile has no FK data), then calls `SchemaFormatter(join_graph=None).format(...)` to render the complete schema with inline FK tags and per-table `Foreign Keys:` blocks.

Used when the database is small enough (or the user/admin has selected `pipeline_mode="full_schema"`) that filtering the schema is unnecessary.

**Emits**: `STATUS` chunk: `"pipeline_mode=full_schema — linker bypassed (N tables, M columns)"`

### Stage 3: SqlGeneratorStage (`name="sql_generator"`)

**File:** `pipeline/generator_stage.py`

Generates SQL from the linked schema and user question.

**Process:**
1. Renders `sql_generation.j2` (a ~160-line prompt with Chain-of-Thought reasoning, JOIN guidance, and rule includes). The prompt uses `{% if few_shot_example %}` to conditionally inject a BIRD-train QA pair.
2. Calls `llm.async_generate(prompt)`.
3. Extracts SQL from the first ` ```sql ``` ` fenced block via regex.

The vendored `pipeline_core` also provides:
- **Candidate generation**: Multiple candidates via temperature shuffle and schema ordering shuffle for diversity.
- **Majority voting**: Groups candidates by result-set equality, picks the largest group.
- **Self-correction**: Tool-calling loop where the LLM writes SQL, executes it, inspects results, and iterates (max 3 turns).
- **Few-shot retrieval**: At runtime, embeds the user's question and performs cosine similarity against a per-DB BIRD-train embedding bank (float16, 1536-dim), returning the top-1 match.

**Emits**: `SQL_GENERATED` with `{sql, iteration=0}`

### Stage 4: SqlValidatorStage (`name="sql_validator"`)

**File:** `pipeline/validator_stage.py`

Validates SQL syntax using **sqlglot** (`sqlglot.parse_one(sql, dialect=...)`). The dialect is resolved from the DialectAdapter's `sqlglot_dialect` property.

- **On failure**: Sets `ctx.state["error"]`, emits `ERROR`, returns `None`.
- **On success**: Clears any stale `"error"`, emits `STATUS("SQL valid")`.

### Stage 5: SqlExecutorStage (`name="sql_executor"`)

**File:** `pipeline/executor_stage.py`

Executes the validated SQL against the user's database.

**Process:**
1. Skips entirely if `ctx.state["error"]` is already set (from validator failure).
2. Resolves the database file path via `DatabaseService.resolve()`.
3. Emits `SQL_EXECUTING`.
4. Calls `DatabaseConnector.execute(sql)` with read-only enforcement:
   - `FORBIDDEN_SQL_RE` regex check (blocks INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/REPLACE).
   - `PRAGMA query_only = ON` (SQLite) or read-only connection (Postgres), reset in `finally`.
   - Fetches up to `SQL_ROW_LIMIT` rows (default 1000).
   - Timeout via `statement_timeout` (Postgres) or `connect_timeout` (SQLite), default 30s.
5. On success: emits `ROWS_RETURNED` with `{columns, rows, row_count, execution_time_ms}`.
6. On failure: sets `ctx.state["error"]`, emits `ERROR`.

### Stage 6: SqlRefinerStage (`name="sql_refiner"`)

**File:** `pipeline/refiner_stage.py`

Iterative error recovery loop (max 2 iterations, configurable via `MAX_REFINEMENT_ITERATIONS`).

**Process:**
1. Passes through if no error flag.
2. For each iteration:
   - Renders `refine_sql.j2` with schema, question, previous SQL, and error message.
   - Calls LLM to generate corrected SQL.
   - Extracts SQL from fenced block.
   - Inline validates (sqlglot parse).
   - Inline executes.
3. On success: clears `ctx.state["error"]`, sets `ctx.state["rows"]`, returns refined SQL.
4. On persistent failure: leaves `ctx.state["error"]` set.

**Buffer-then-flush pattern**: Errors are buffered during execution attempts and only flushed to the SSE stream after all refinement iterations are exhausted. This prevents the frontend from showing transient errors that the refiner subsequently fixes.

**Emits per iteration**: `SQL_GENERATED (iteration=N)` → `SQL_EXECUTING` → `ROWS_RETURNED` (on success)

### Stage 7: AnswerSynthesizerStage (`name="answer_synthesizer"`)

**File:** `pipeline/synthesizer_stage.py`

Synthesizes the final natural-language answer from the question, SQL, and result rows.

**Process:**
1. Skips if `ctx.state["error"]` is set.
2. Renders `answer_synthesizer.j2` with question, DDL, SQL, columns, and rows.
3. Calls `llm.async_generate_stream(prompt)` -- **streaming path**.
4. For each non-empty delta: emits `answer_delta` chunk (`{text}`) so the frontend renders materializing text live. This departs from the "stage writes state, route emits" pattern deliberately.
5. On completion: emits terminal `ANSWER_GENERATED` with the full answer text.

**Footnote format**: Answers use `[^1]`, `[^2]` citation format matching the frontend's inline footnote renderer.

**Graceful degradation**: If LLM streaming fails, falls back to `"Query returned {row_count} rows."`.

**Emits**: `answer_delta` (multiple, during streaming) → `ANSWER_GENERATED` (from route layer)

---

## 4. SSE Chunk Taxonomy

Every chunk on the wire uses a strict envelope:

```json
{"type": "<ChunkType>", "data": {<typed payload>}, "conversation_id": "<uuid>", "timestamp": 1713123456.789}
```

The `ChunkType` enum defines ~50 typed chunk types organized into four tiers:

### Tier 1: Lifecycle (every chat turn)

| Type | Description |
|---|---|
| `status` | Progress message; may include `rag_context` or `agent`/`phase` data |
| `error` | Error with code and detail |
| `metrics` | Terminal chunk: `{latency_ms, prompt_tokens, output_tokens, total_tokens, model}` |

### Tier 2: Generic Tool Protocol (agentic mode)

| Type | Description |
|---|---|
| `tool_call` | Tool invocation: `{tool_name, args, llm_reasoning}` |
| `tool_result` | Tool result: `{tool: name, result: json_string}` |

### Tier 3: Pipeline Transparency (one per stage)

| Type | Stage | Payload |
|---|---|---|
| `profile_loaded` | Profiler | `{db_id, table_count, column_count, from_cache}` |
| `schema_linking_started` | SchemaLinker | -- |
| `candidate_sqls_generated` | SchemaLinker | `{candidates: [{sql, tables, columns}, ...]}` |
| `literals_extracted` | SchemaLinker | `{literals: [{value, matched_columns}, ...]}` |
| `semantic_matches` | SchemaLinker | `{matches: [{column, similarity}, ...]}` |
| `join_paths_added` | SchemaLinker | `{paths: [{from_table, to_table, via_column}, ...]}` |
| `linked_schema_final` | SchemaLinker | `{schema_text, table_count, column_count}` |
| `sql_generated` | SqlGenerator / SqlRefiner | `{sql, iteration}` |
| `sql_executing` | SqlExecutor | -- |
| `rows_returned` | SqlExecutor | `{columns, rows, row_count, execution_time_ms}` |
| `answer_generated` | Route layer | `{answer}` |
| `answer_delta` | Synthesizer | `{text}` (incremental, during streaming) |
| `few_shot_retrieved` | Preflight | `{question, sql, similarity}` |

### Tier 4: Orchestration Transparency (agentic mode)

| Type | Description |
|---|---|
| `auto_routed` | Mode classification result: `{from_mode, to_mode, reason}` |
| `stats_context` | Pre-computed statistics injected into prompt |
| `clarification` | Clarifying question: `{question, skip_allowed}` |
| `orchestrator_plan` | Enrichment plan: `{reasoning, tasks: [{id, agent, category, question, depends_on}]}` |
| `agent_trace` | Per-task execution details with `steps` array |
| `enrichment_trace` | Citation source: `{source_index, category, question, sql, answer, steps}` |
| `insight` | Synthesized cited response (agentic mode only) |

### Profiling Upgrade Types

Additional types for the profiling pipeline:
`profile_stage_started`, `profile_stage_completed`, `profile_progress`, `profile_cost_estimate`, `profile_done`, `profile_error`, `sample_questions_ready`.

### EventEmitter

`EventEmitter` in `sse/emitter.py` manages per-request SSE streaming:
- One emitter per request, stored in `app.state.user_notification_emitters` keyed by user_id.
- `emit(chunk_type, payload)` wraps in `ChatChunk` envelope, puts on `asyncio.Queue(maxsize=256)`.
- Queue uses oldest-drop back-pressure when full (sampled warnings every 10th drop).
- `stream()` async generator yields `chunk.to_json()` until `None` sentinel, then `"[DONE]"`.
- `EventSourceResponse` wraps the generator, framing each yield as `data: ...\n\n`.
- SSE idle reaper (60s tick) evicts entries idle >15 minutes with no subscribers.

---

## 5. Pipeline Modes

### "linked" (default)

The `SchemaLinkerStage` runs the full 5-signal linking process. This is the default for most databases because it reduces the schema to only relevant tables/columns, saving LLM prompt tokens and improving SQL generation accuracy.

### "full_schema"

The `FullSchemaStage` bypasses all linker logic and presents the complete schema to the SQL generator. Best for small databases (fewer than ~10 tables) where filtering is unnecessary overhead.

### Mode Selection Precedence

1. **Admin override**: `pipeline_mode` in the request body (admin-only; returns 403 for non-admins).
2. **Per-DB default**: `pipeline_mode_default` on the database record.
3. **System default**: `"linked"`.

---

## 6. Profiling Pipeline

A separate pipeline handles database profiling -- the one-time (or refresh-on-demand) process of extracting schema, collecting statistics, generating summaries, and building search indexes.

### 7 Steps

1. **Schema Extract**: `SchemaExtractor.extract()` via `PRAGMA table_info/foreign_key_list` (SQLite) or `information_schema` (Postgres).
2. **Stats Collect**: `StatsCollector` runs per-column aggregation queries (COUNT, COUNT DISTINCT, MIN, MAX, LIMIT 20 samples).
3. **Join Graph Build**: `JoinGraphBuilder` constructs a graph from declared FKs + implicit edges.
4. **Summary Generate**: `SummaryGenerator` makes async LLM calls (short + long summary per column), semaphore-limited (concurrency=2 via `PROFILE_MAX_CONCURRENCY`).
5. **Quirk Detect**: `QuirkEnricher` applies rule-based heuristics and LLM enrichment for enum labels and semantic hints.
6. **LSH Build**: MinHash-based Locality-Sensitive Hashing index for literal value matching.
7. **Vector Build**: `VectorBuilder` embeds column descriptions into a cosine-similarity `VectorIndex`.

### Cost Gate Handshake

Before LLM profiling begins, a cost estimate is computed based on column count and batch size. The system emits a `profile_cost_estimate` chunk to the frontend. The user must explicitly confirm before LLM calls proceed. Columns exceeding `PROFILING_MAX_COLUMNS_FOR_LLM` (default 500) auto-disable LLM profiling.

### Batched LLM Prompts

Instead of one LLM call per column, profiling uses batched prompts (20 columns per call). This reduces API costs from O(columns) to O(columns/batch_size) and avoids rate limiting.

### Per-DB Output Caching

Profiling results are cached in the metadata DB via `ProfileService`. Subsequent requests load the cached `DatabaseProfile` instead of re-profiling. The cache is invalidated when the database schema changes.

### Rate Limiting

Per-user profiling is rate-limited to `PROFILE_MAX_PER_USER_PER_DAY` (default 10) per day, preventing abuse.

---

## 7. Token Tracking

A single LLM instance is shared across all pipeline stages. Its `input_tokens_used` / `output_tokens_used` accumulators are incremented by every LLM call. The route layer reads them once at the end for the terminal `metrics` chunk.

LLM concurrency is controlled by a module-level `asyncio.Semaphore`:
- General calls: `LLM_MAX_CONCURRENCY` (default 3).
- Profiling calls: `PROFILE_MAX_CONCURRENCY` (default 2, stricter to avoid starving chat requests).

---

## 8. Conversation Persistence

### In-Memory Layer (`services/conversation_store.py`)
- Thread-safe `OrderedDict` keyed by `(session_id, conversation_id)`.
- Holds `Conversation` objects with `messages[]` and `chunks[]` (SSE replay buffer).
- Lost on instance recycle (v1 tradeoff -- acceptable for Cloud Run's stateless model).

### Durable Layer (`orchestration/service.py`)
- `record_conversation_snapshot()` upserts `conversations` row + inserts user + assistant `messages` rows (with `chunks_json`) in a single transaction.
- Best-effort only: guarded by user-existence check; failures logged and swallowed.

### Fire-and-Forget Pattern

Persistence is intentionally asynchronous to keep SSE latency low:

```
yield "[DONE]"  # client stops spinner immediately

asyncio.ensure_future(
    asyncio.to_thread(_persist_response, ...)
)
```

`[DONE]` is yielded before `asyncio.ensure_future()` is called, so the client's spinner stops as soon as the answer is delivered. The DB write happens after, without blocking the user.
