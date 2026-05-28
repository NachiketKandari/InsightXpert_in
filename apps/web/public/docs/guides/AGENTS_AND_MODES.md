# InsightXpert.ai: Agents, Modes & Orchestration

This document describes every agent, analysis mode, and orchestration pipeline in InsightXpert.ai -- what each component does, when it fires, why it exists, and what types of questions suit each mode.

---

## Table of Contents

1. [Mode Overview](#mode-overview)
2. [Mode Router](#mode-router)
3. [Agentic Orchestrator](#agentic-orchestrator)
4. [Agent Types](#agent-types)
5. [Enrichment Phases](#enrichment-phases)
6. [Tools](#tools)
7. [Memory](#memory)
8. [Dual-Mode Dispatch](#dual-mode-dispatch)

---

## 1. Mode Overview

InsightXpert.ai supports three analysis modes selected via the `agent_mode` field of `ChatRequest`:

| Mode | API Value | Description |
|---|---|---|
| **Basic** | `"basic"` | Pipeline only. Direct question-to-SQL-to-answer. No enrichment. |
| **Agentic** | `"agentic"` | Pipeline + enrichment. Analyst answers first, then an evaluator decides if deeper analysis is needed, runs parallel sub-tasks, and synthesizes a cited response. |
| **Auto** | `"auto"` | LLM classifier decides between basic and agentic per-request. |

### Basic Mode

```
Question → Pipeline (7 stages) → Answer → Done
```

The pipeline runs end-to-end: profile loading, schema linking, SQL generation, validation, execution, refinement, and answer synthesis. No orchestration, no enrichment, no multi-agent coordination. The user sees the pipeline's SSE chunks in real time.

**Best for:**
- Simple factual lookups: "How many orders were placed last month?"
- Single-metric queries: "What's the average order value?"
- Quick counts and aggregations: "Top 10 customers by revenue"
- When you already know the answer is in one query

### Agentic Mode

```
Question → Pipeline (analyst answers immediately)
  → Enrichment Evaluator (should we dig deeper?)
    → [If yes] DAG Execution (1-4 parallel sub-tasks)
      → Response Synthesizer (combine with citations)
        → Insight Quality Gate (worth saving?)
```

The analyst's pipeline runs first and the user sees results immediately. Then an evaluator LLM call decides if the answer would benefit from enrichment. If yes, it plans 1-4 targeted sub-tasks, executes them with maximum parallelism (respecting dependencies), and synthesizes everything into a cited response.

**Best for:**
- Analytical questions: "What's driving the increase in churn?"
- Comparative questions: "How does Q1 compare to Q4?"
- Trend questions: "Is customer acquisition growing?"
- Questions where one query answers the surface but not the "so what?"

### Auto Mode

The system uses a lightweight LLM classifier (Gemini flash-lite) to decide per-request whether to use basic or agentic mode. The classifier evaluates question complexity, the presence of comparative/analytical language, and whether a single query is likely sufficient. Server-side re-classification acts as defense-in-depth even when the frontend pre-routes.

**Best for:** General use where you want the system to automatically choose the right depth of analysis.

---

## 2. Mode Router

### Auto-Mode Classification

When `agent_mode="auto"`, the preflight step calls `classify_mode()`:

```
POST /chat with agent_mode="auto"
  → _preflight_concurrent():
      classify_mode() runs in parallel with profile loading and few-shot retrieval
```

`classify_mode()` in `routes/chat.py`:
1. Renders `mode_router.j2` prompt with the user's question.
2. Calls `gemini-3.1-flash-lite-preview` (fast/cheap model).
3. Parses the JSON response: `{mode: "basic"|"agentic", reason: "..."}`.
4. On any failure (timeout, parse error): defaults to `"agentic"` (bias toward correctness).

The classification result is emitted as an `auto_routed` chunk so the frontend can show: _"Auto-routed to agentic mode -- this question needs deeper analysis."_

### Server-Side Re-Classification (Defense-in-Depth)

Even when the frontend pre-routes via `POST /chat/route` (which returns a mode suggestion without running the pipeline), the server re-classifies `agent_mode="auto"` on the actual `/chat` request. This prevents client-side bugs or stale pre-routing from forcing incorrect modes.

### mode_router.py

The classification prompt template evaluates:
- Question complexity (single fact vs. multi-faceted analysis).
- Comparative/analytical language signals.
- Whether a single SQL query is likely sufficient.
- Historical patterns from similar questions.

---

## 3. Agentic Orchestrator

The agentic orchestrator lives in `vendored/agents_core/orchestrator.py` and is invoked from our `routes/chat.py` via `_run_orchestrator()`.

### orchestrator_loop()

The top-level `orchestrator_loop()` supports three modes:

**basic:**
```
analyst_loop() → stream chunks directly
```

**agentic:**
```
analyst_loop() → evaluate_for_enrichment() →
  if enrichment needed: plan_tasks() → execute_dag() → generate_response() →
  evaluate_insight_quality()
  else: analyst answer stands
```

**deep** (experimental, not exposed in production UI):
```
_extract_dimensions() || analyst_loop() →
  execute_dag(enrichment) → _deep_synthesize() →
  evaluate_for_investigation() → execute_dag(investigation) → _investigation_synthesize()
```

### How Our Code Composes

Our `analyst_loop` adapter (`agents/analyst.py`) wraps the 7-stage pipeline as an `analyst_loop` implementation. It is injected into the vendored orchestrator via `functools.partial`:

```python
_run_orchestrator():
    analyst_impl = functools.partial(analyst_loop, ...)
    async for chunk in orchestrator_loop(analyst_impl=analyst_impl, ...):
        yield _vendored_to_envelope(chunk)
```

This adapter:
1. Builds the same `default_pipeline()` as the legacy path.
2. Creates an internal `EventEmitter` and `PipelineContext`.
3. Fires `_drive_pipeline()` as an asyncio task.
4. Translates pipeline-envelope chunks to vendored-flat chunks via `_to_vendored()`.
5. Injects synthetic `tool_call`/`tool_result` pairs so the vendored `AnalystCollector` sees them.
6. Buffers errors during execution so the refiner can recover without the orchestrator latching `had_error=true`.

### orchestrator_planner.py

The planner module handles task decomposition and enrichment evaluation:

- **`plan_tasks(question, ddl, documentation)`**: Decomposes a complex question into a DAG of sub-tasks. Falls back to a single `sql_analyst` task on error.
- **`evaluate_for_enrichment(sql, rows, answer)`**: Decides if the analyst's answer needs enrichment. Returns `None` if the answer is sufficient.
- **`evaluate_for_investigation(synthesis)`**: Detects gaps in a synthesized response. Returns `None` if no gaps found.
- **`evaluate_insight_quality(synthesis)`**: Gates whether the final response is worth persisting as an insight.

### DAG Executor (`dag_executor.py`)

Executes an `OrchestratorPlan` with maximum parallelism while respecting DAG dependencies:

1. Finds all tasks whose `depends_on` list is empty or fully satisfied.
2. Launches them all concurrently with `asyncio.gather()`.
3. As tasks complete, checks for newly unblocked tasks and launches those.
4. Repeats until all tasks are done, errored, or skipped.
5. On task failure: marks downstream tasks as `skipped` recursively.

Circular dependencies are detected at validation time via Kahn's algorithm. If a cycle is found, all dependency links are removed and tasks run in parallel.

Task types:
- **`sql_analyst`**: Runs the analyst pipeline for a sub-question. Returns `SubTaskResult` with SQL, rows, and answer.
- **`quant_analyst`**: Runs statistical analysis on upstream results. Returns `SubTaskResult` with statistical findings.

---

## 4. Agent Types

### Analyst Agent

**Used in:** All modes (always runs first).

The primary SQL analyst. Converts natural language into SQL, executes the query, and narrates the results. In the vendored implementation, it runs a tool-calling loop with RAG retrieval, semantic column pruning, and an iterative LLM loop (up to 25 iterations).

In our adapter, it wraps the 7-stage pipeline, providing the same interface the orchestrator expects while using the pipeline engine for execution.

**Pipeline:** RAG retrieval → prompt assembly → pipeline execution → auto-save Q&A pair.

### Quant Analyst

**Used in:** Agentic mode (as a downstream enrichment sub-task).

A statistical analysis agent that receives upstream SQL results and applies quantitative analysis beyond what SQL can do. Runs in a tool-calling loop (up to 5 iterations) with access to statistical tools.

**Tools:** `compute_descriptive_stats`, `test_hypothesis`, `compute_correlation`, `fit_distribution`, `run_python`, plus `run_sql` for additional data fetching.

**Setup:** Upstream results from depended-on `sql_analyst` tasks are merged into a DataFrame. The `quant_analyst_system.j2` prompt receives DDL, documentation, upstream SQL, and a results summary.

### Clarifier

**Used in:** Agentic mode (when `clarification_enabled=True`).

A lightweight, single-shot LLM call that runs **before** the analyst. It checks whether the user's question is genuinely ambiguous -- meaning multiple reasonable interpretations would produce different SQL queries.

**Decision logic:**
- If clear: `{"action": "execute"}` → analyst proceeds normally.
- If ambiguous: `{"action": "clarify", "question": "..."}` → user sees a clarification question.

On any error, falls back to `"execute"` -- never blocks the user.

**Flow:**
1. LLM calls `clarify({"question": "Did you mean X or Y?"})`.
2. The analyst loop detects the `clarify` tool, emits a `clarification` chunk, and returns.
3. The frontend renders the question with two options: answer it, or click "Just answer" (sets `skip_clarification=true`).
4. If the user answers, their clarification is appended to the question on the next request.

### Deep Think Agent

**Used in:** Deep mode (experimental, not exposed in production UI).

Extends the agentic flow with a 5W1H framework:

1. **Dimension Extraction** (15s timeout): Maps the question onto WHO/WHAT/WHEN/WHERE/HOW dimensions.
2. **Analyst**: Pipeline runs unchanged; user sees immediate results.
3. **Targeted Enrichment**: Pre-planned enrichment tasks execute via DAG.
4. **Deep Synthesis** (60s timeout): `deep_synthesizer.j2` produces a 5W1H-structured insight.
5. **Auto-Investigation**: Detects gaps in the synthesis and runs follow-up queries.
6. **Re-Synthesis**: Integrates investigation findings into the prior synthesis, focusing on what changed.

### Response Generator

**Used in:** Agentic mode (Phase 4, after enrichment).

Takes evidence from all sub-tasks (original analyst + enrichment agents) and synthesizes a single, cited response suitable for leadership consumption.

**Citation system:**
- Source `[^1]` = original analyst answer.
- Source `[^2]`, `[^3]`, etc. = enrichment sub-task results.
- Each source has a label (e.g., "Comparative Context", "Root-Cause Analysis").

**Output structure:**
1. Direct answer to the question.
2. Key evidence with `[^N]` citations.
3. Contextual analysis.
4. Root-cause hypothesis (if applicable).
5. Business recommendations with specific data thresholds.
6. Suggested follow-up questions.

On LLM failure, `_fallback_answer()` concatenates individual agent answers separated by `---` dividers.

---

## 5. Enrichment Phases

Agentic mode runs in distinct phases:

### Phase 1: Analyst (Immediate Results)

The analyst pipeline runs with the original question. Every chunk is yielded directly to the SSE response -- the user sees SQL, results, and the answer immediately, before any enrichment begins.

Simultaneously, the orchestrator collects: `analyst_sql`, `analyst_rows`, `analyst_answer`, and `analyst_had_error` flag.

If the analyst had an error or produced no answer, the orchestrator stops here. No enrichment is attempted.

### Phase 2: Enrichment Evaluation

A `status` chunk announces that deeper analysis is being evaluated.

`evaluate_for_enrichment()` makes a single LLM call (no tools, 60s timeout) with:
- The user's question.
- The analyst's SQL, rows summary, and answer.
- DDL and documentation.
- Conversation history.
- RAG context (similar past Q&A pairs).

**Decision criteria:**
- `"enrich": false` for simple factual questions.
- `"enrich": true` when comparative context, temporal trends, root-cause analysis, or segmentation would materially improve the answer.

On any failure (timeout, JSON parse error, validation error), returns `None` -- the analyst answer stands.

### Phase 3: DAG Execution

An `orchestrator_plan` chunk lists the enrichment tasks. The DAG executor runs tasks with maximum parallelism.

**Enrichment categories:**

| Category | Label | When Used |
|---|---|---|
| `comparative_context` | Comparative Context | A metric is shown without benchmarks |
| `temporal_trend` | Temporal Trend | Data changes over time but the analyst showed a snapshot |
| `root_cause` | Root-Cause Analysis | An anomaly or outlier needs explanation |
| `segmentation` | Segmentation | An aggregate answer would be more useful broken down by dimension |

`on_task_start` and `on_task_complete` callbacks accumulate `status` and `agent_trace` chunks, which are yielded after the DAG completes.

### Phase 4: Evidence Assembly and Synthesis

After all tasks complete (or error), evidence blocks are assembled:
- Source [1]: Original analyst answer (question, SQL, rows summary, answer).
- Source [2..N]: Each successful enrichment task (category label, question, SQL, rows summary, answer).

The response generator synthesizes these into a cited response. The synthesized markdown is emitted as an `insight` chunk.

### Phase 5: Enrichment Traces

One `enrichment_trace` chunk is emitted per source:
- Source [1]: Original analyst (category "SQL Analysis", question, SQL, answer).
- Source [2..N]: Each enrichment task (category label, question, SQL, answer, full trace steps).

The frontend's `CitationLink` component renders `[^N]` references as clickable links that open a `TraceModal` showing the source's category, question, SQL, and execution steps.

---

## 6. Tools

The vendored `agents_core` provides a tool system used by the analyst and quant analyst loops.

### Tool Architecture

```python
class Tool(ABC):
    name: str
    description: str
    def get_args_schema(self) -> dict: ...
    async def execute(self, context: ToolContext, args: dict) -> str: ...
    def get_definition(self) -> dict: ...  # OpenAI function-calling schema

class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get_schemas(self) -> list[dict]: ...  # For LLM tool-calling
    async def execute(self, name, args, context) -> str: ...
```

### ToolContext

```python
@dataclass
class ToolContext:
    db: DatabaseConnector
    rag: VectorStoreBackend | None
    row_limit: int = 1000
    analyst_results: list[dict] | None = None
    analyst_sql: str | None = None
    allowed_tables: list[str] | None = None
    dataset_id: str | None = None
```

### Analyst Tools

| Tool | Purpose |
|---|---|
| `run_sql` | Execute read-only SQL with visualization hints |
| `get_schema` | Return CREATE TABLE DDL or per-table info |
| `search_similar` | Search RAG collections (qa_pairs, ddl, docs) |
| `clarify` | Ask clarifying question (conditional, only when `clarification_enabled=True`) |

### Quant Analyst Tools

| Tool | Purpose |
|---|---|
| `compute_descriptive_stats` | Mean, median, std, quartiles, skewness, kurtosis |
| `test_hypothesis` | Chi-squared, t-test, Mann-Whitney, ANOVA, z-proportion |
| `compute_correlation` | Pearson, Spearman, Kendall |
| `fit_distribution` | Fit to normal, exponential, lognormal, gamma, Weibull |
| `run_python` | Sandboxed Python execution with preloaded scientific libraries |
| `run_sql` | Additional data fetching when upstream data is insufficient |

### Advanced Tools

Available in `advanced_tools.py`:

**Time-series:** `compute_time_series_slope`, `compute_area_under_curve`, `compute_percentage_change`, `detect_peaks`, `detect_change_points`.

**Fraud/risk:** `score_fraud_risk`, `detect_amount_anomalies`, `test_temporal_fraud_clustering`, `compute_bank_pair_risk`.

**General:** `compute_percentile_rank`, `compute_concentration_index`, `test_benford_law`.

### SQL Guard (D-053 Dual Enforcement)

All SQL execution goes through two independent enforcement layers:
1. **Regex blocklist**: `FORBIDDEN_SQL_RE` blocks INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/REPLACE/MERGE/GRANT/REVOKE/ATTACH/DETACH before execution.
2. **Connection-level**: `PRAGMA query_only = ON` (SQLite) or read-only connection (Postgres), enforced by the database engine itself.

### Error Sanitization

`ToolRegistry.execute()` wraps every tool call in try/except and returns sanitized error JSON. Python tracebacks are never sent to the LLM or user -- only the exception message string. The LLM receives clean error strings and can adjust its next tool call accordingly.

---

## 7. Memory

### Conversation Memory Store

The in-memory `ConversationStore` (`services/conversation_store.py`):
- Thread-safe `OrderedDict` keyed by `(session_id, conversation_id)`.
- Max 500 conversations; LRU eviction when exceeded.
- TTL-based expiry at access time (configurable, default 2 hours).
- Stores condensed history: user messages + assistant final answers (no tool intermediaries).
- Returns last 20 turns for LLM context injection.

On cache miss, the store hydrates from the durable `PersistentConversationStore` (Postgres-backed), loading full message history with chunks.

### RAG Store Interface

The `VectorStoreBackend` Protocol in `vendored/agents_core/rag/base.py` defines 14 methods for CRUD across collections: `qa_pairs`, `ddl`, `docs`, `findings`, `column_metadata`.

Our implementation uses **pgvector** (Postgres extension), not ChromaDB. The pgvector-backed adapter (`rag/pgvector_store.py`) implements the Protocol with Postgres-native vector operations.

**Deduplication:** Documents are keyed by `SHA-256(content)[:16]`. Writes use upsert, so duplicate inserts are idempotent.

**Auto-save flywheel:** After every successful analyst answer, the (question, SQL) pair is persisted with `sql_valid=True`. Over time, frequently asked questions accumulate accurate few-shot examples, improving future SQL generation without manual curation.

---

## 8. Dual-Mode Dispatch

The chat route (`routes/chat.py`) dispatches between two code paths depending on `agent_mode`:

### Legacy Pipeline Path (`agent_mode is None`)

`_build_pipeline_and_ctx()` constructs a `Pipeline` with 7 stages, then `_run_pipeline()` fires as a background `asyncio.create_task`. The route returns `EventSourceResponse` immediately.

### Orchestrator Path (`agent_mode in {"basic", "agentic"}`)

`_run_orchestrator()` wraps our pipeline as an `analyst_loop` adapter (via `functools.partial`) and passes it to the vendored `orchestrator_loop(analyst_impl=...)`. The orchestrator runs: analyst → evaluate enrichment → DAG execution → synthesize → quality gate.

### Preflight Parallelism

Three independent operations are raced via `asyncio.TaskGroup` before pipeline dispatch:

| Operation | What It Does | Failure Behavior |
|---|---|---|
| `prefetch_profile()` | Loads `DatabaseProfile` from Postgres (or process cache) | Returns `None`; ProfilerStage handles cold-cache normally |
| `classify_mode()` | Calls Gemini flash-lite with `mode_router.j2` (only when `agent_mode="auto"`) | Defaults to `"agentic"` |
| `prefetch_few_shot_example()` | Embeds user question, cosine similarity against per-DB BIRD-train bank | Returns `None` |

Each operation has its own try/except -- one failure never cancels the others. Total wall time = max(profile, classify, few_shot), cutting steady-state latency by up to one DB round-trip.

### ChatChunk Translation

The vendored `orchestrator_loop` yields flat `ChatChunk` objects (from `vendored/agents_core/api/models.py`). `_vendored_to_envelope()` translates these into our strict four-field envelope (`{type, data, conversation_id, timestamp}`), dropping internal-only types (`"sql"`, `"answer"`) and unknown types silently.

---

## 9. LLM Abstraction

### Provider-Agnostic Factory

The LLM layer in `vendored/agents_core/llm/` uses a structural Protocol:

```python
class LLMProvider(Protocol):
    model: str
    async def chat(messages: list[dict], tools: list[dict] | None = None,
                   force_tool_use: bool = False) -> LLMResponse
```

`LLMResponse`: `content`, `tool_calls[]`, `input_tokens`, `output_tokens`.

Message format is OpenAI-style throughout (roles: `system`, `user`, `assistant`, `tool`).

### Provider Implementations

- **`DeepSeekProvider`**: Wraps OpenAI SDK pointed at DeepSeek API. Native format, no message translation.
- **`GeminiProvider`**: Wraps `google-genai` SDK. Translates messages/tools to Gemini format and back. Generates synthetic UUID tool call IDs (Gemini doesn't return them natively).
- **`OllamaProvider` / `VertexAIProvider`**: Referenced by the factory but not present in the vendored tree.

### Factory

`create_llm(provider_name, settings)` dispatches on `"gemini"`, `"deepseek"`, `"ollama"`, `"vertex_ai"`. The active provider is set via `LLM_PROVIDER` env var.

Both providers support chat + embeddings. The `pipeline_core` side uses simpler single-turn `BaseLLM` (generate/embed), while `agents_core` uses the richer chat Protocol with tool calling.

---

## 10. Error Handling and Fallbacks

Every component degrades gracefully:

| Component | On Failure | Behavior |
|---|---|---|
| RAG retrieval | Warning logged | Analyst proceeds without few-shot examples |
| Mode classifier | Warning logged | Defaults to `"agentic"` |
| Clarifier | Warning logged | Proceeds to analyst (no clarification) |
| Enrichment evaluator | Warning logged | Analyst answer stands (no enrichment) |
| Quant analyst sub-task | Task marked "error" | Synthesis uses available results, skips failed task |
| Response synthesis | Falls back | Returns concatenated agent answers |
| Insight quality check | Default | Saves as insight (`is_insight=True`) |
| Dimension extraction | Warning logged | Falls back to agentic-mode pipeline |

**Timeouts:**

| Component | Timeout |
|---|---|
| Enrichment evaluator | 60 seconds |
| Dimension extraction | 15 seconds |
| Synthesizers | 60 seconds |
