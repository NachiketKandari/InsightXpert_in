# InsightXpert.ai Agent Tools Reference

InsightXpert.ai agents use a structured tool system to interact with databases, perform statistical analysis, and execute custom Python code. This document covers every tool, its arguments, return values, and the safety mechanisms that protect user data.

---

## 1. Tool Architecture

### Tool Protocol

Tools implement an abstract base class from `vendored/agents_core/tool_base.py`:

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def get_args_schema(self) -> dict: ...
    # Returns a JSON Schema dict describing the tool's parameters

    @abstractmethod
    async def execute(self, context: ToolContext, args: dict) -> str: ...
    # Returns a JSON-encoded string result

    def get_definition(self) -> dict:
        """Build the OpenAI function-calling schema dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.get_args_schema(),
        }
```

### ToolContext

Tools receive a shared context with access to database, RAG, and upstream results:

```python
@dataclass
class ToolContext:
    db: DatabaseConnector          # Database connection for run_sql
    rag: VectorStoreBackend | None # Vector store for search_similar
    row_limit: int = 1000          # Max rows per query
    analyst_results: list[dict] | None = None  # Upstream rows for quant analyst
    analyst_sql: str | None = None             # Upstream SQL for quant analyst
    allowed_tables: list[str] | None = None    # Table access control
    dataset_id: str | None = None              # Dataset identifier
```

### ToolRegistry

Tools are registered into a typed dispatch:

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get_schemas(self) -> list[dict]: ...   # JSON schemas for LLM function-calling
    async def execute(self, name, args, context) -> str: ...  # Sanitized errors only
```

Unknown tool names return `{"error": "Unknown tool: ..."}` without raising. Exceptions inside `tool.execute()` are caught and returned as JSON error strings -- tracebacks are never sent to the LLM or user.

### Tool Registration Pattern

Tools are registered by factory functions:

```python
# Analyst tools (vendored/agents_core/tools.py)
def default_registry() -> ToolRegistry: ...

# Quant analyst tools (vendored/agents_core/stat_tools.py)
def _quant_registry() -> ToolRegistry: ...
```

The `clarify` tool is conditionally registered only when `clarification_enabled=True`.

---

## 2. Database Tools

### run_sql

Execute a read-only SELECT query against the connected database.

| Arg | Type | Required | Description |
|---|---|---|---|
| `sql` | string | yes | SQL SELECT query to execute |
| `visualization` | enum | no | Chart type hint: `bar`, `pie`, `line`, `grouped-bar`, `table` |
| `x_column` | string | no | Column to use as x-axis / categories |
| `y_column` | string | no | Column to use as y-axis / values |

**Returns:**
```json
{"rows": [...], "row_count": 42}
```

**Enforcement:**
1. `FORBIDDEN_SQL_RE` regex check before execution.
2. `PRAGMA query_only = ON` (SQLite) or read-only connection (Postgres).
3. Row limit: `SQL_ROW_LIMIT` (default 1000).
4. Timeout: `SQL_TIMEOUT_SECONDS` (default 30s).

**Visualization hints:** When provided, the frontend renders the result as a chart using the specified type and axis columns. If omitted, the frontend defaults to a table view.

---

### get_schema

Return the CREATE TABLE DDL statements for database tables.

| Arg | Type | Required | Description |
|---|---|---|---|
| `tables` | string[] | no | Specific table names; omit to get all tables |

**Returns (all tables):** Full DDL string with CREATE TABLE statements for every table.

**Returns (specific tables):** Array of objects with `name`, `ddl`, `row_count`, and `column_count` per table.

This tool is used by the analyst when it needs to verify column names, check data types, or understand foreign key relationships before writing SQL.

---

### search_similar

Search the RAG (Retrieval-Augmented Generation) knowledge base for similar past queries, DDL, or documentation.

| Arg | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Search query text |
| `collection` | enum | yes | `qa_pairs`, `ddl`, or `docs` |

**Returns:** Array of matching items with similarity scores, content, and metadata.

**Backend:** Uses **pgvector** (Postgres extension) for vector similarity search. Documents are embedded using the configured embedding model and stored as pgvector columns. Similarity is computed via cosine distance.

**RAG Collections:**

| Collection | Content | Populated By |
|---|---|---|
| `qa_pairs` | Question-to-SQL pairs | Trainer (seed examples) + auto-save after successful answers |
| `ddl` | CREATE TABLE statements | Trainer from schema extraction |
| `docs` | Business-context documentation | Trainer from database documentation |

**Deduplication:** Every document ID is `SHA-256(content)[:16]`. Writes use upsert, so inserting the same content twice is a no-op. The trainer is safe to call on every startup.

**Auto-save flywheel:** After every successful analyst answer, the (question, SQL) pair is persisted with `sql_valid=True`. Over time, frequently asked questions accumulate accurate few-shot examples, improving future SQL generation.

---

### clarify

Ask the user a clarifying question when the request is ambiguous. Only registered when `clarification_enabled=True`.

| Arg | Type | Required | Description |
|---|---|---|---|
| `question` | string | yes | The clarifying question to ask the user |

**Returns:**
```json
{"clarification": "Did you mean revenue before or after discounts?"}
```

When the analyst loop detects a `clarify` tool call, it stops execution and emits a `clarification` chunk. The frontend renders the question with two options: answer it, or click "Just answer" (sets `skip_clarification=true`).

**Prompt guidance:** When `clarification_enabled=True`, the system prompt instructs the LLM to use `clarify` when the question references a column or concept that doesn't exist in the schema, and to suggest the closest available alternative.

---

## 3. Statistical Tools

Statistical tools are available to the quant analyst when running as an enrichment sub-task. They operate on upstream SQL results passed via `ToolContext.analyst_results` (converted to a pandas DataFrame).

### compute_descriptive_stats

Compute descriptive statistics for a numeric column.

| Arg | Type | Required | Description |
|---|---|---|---|
| `column` | string | yes | Column name from the analyst results |

**Returns:**
```json
{
  "count": 15000,
  "mean": 2450.32,
  "std": 1200.15,
  "min": 100.0,
  "q1": 1500.0,
  "median": 2200.0,
  "q3": 3100.0,
  "max": 9800.0,
  "skewness": 1.24,
  "kurtosis": 3.15
}
```

---

### test_hypothesis

Run a statistical hypothesis test on the analyst results.

| Arg | Type | Required | Description |
|---|---|---|---|
| `test` | enum | yes | `chi_squared`, `t_test`, `mann_whitney`, `anova`, `z_proportion` |
| `column` | string | varies | Primary numeric column (t_test, mann_whitney, anova) |
| `group_column` | string | varies | Column to split groups (t_test, mann_whitney, anova) |
| `group_a` | string | varies | Value for group A (t_test, mann_whitney) |
| `group_b` | string | varies | Value for group B (t_test, mann_whitney) |
| `category_col_1` | string | chi_sq | First categorical column |
| `category_col_2` | string | chi_sq | Second categorical column |
| `count_column` | string | optional | Pre-aggregated counts column (chi_squared only) |
| `count_success` | int | z_prop | Number of successes |
| `count_total` | int | z_prop | Total trials |
| `hypothesized_proportion` | float | optional | H0 proportion for z_proportion (default 0.5) |

**Returns per test:**

- **chi_squared**: `statistic`, `p_value`, `dof`, `effect_size_cramers_v`, `significant_at_005`
- **t_test**: `statistic`, `p_value`, `effect_size_cohens_d`, group means and sizes, `significant_at_005`
- **mann_whitney**: `statistic`, `p_value`, `effect_size_r`, group sizes, `significant_at_005`
- **anova**: `statistic`, `p_value`, `effect_size_eta_squared`, `num_groups`, `significant_at_005`
- **z_proportion**: `statistic`, `p_value`, `observed_proportion`, `hypothesized_proportion`, `sample_size`, `significant_at_005`

All tests report `significant_at_005: true/false` for easy interpretation by the LLM.

---

### compute_correlation

Compute correlation between two numeric columns.

| Arg | Type | Required | Description |
|---|---|---|---|
| `column_x` | string | yes | First numeric column |
| `column_y` | string | yes | Second numeric column |
| `method` | enum | optional | `pearson` (default), `spearman`, `kendall` |

**Returns:**
```json
{
  "method": "pearson",
  "correlation": 0.68,
  "p_value": 0.0001,
  "n": 15000,
  "significant_at_005": true
}
```

Pearson measures linear correlation (assumes normal distribution). Spearman measures monotonic relationship (rank-based, robust to outliers). Kendall measures ordinal association (more conservative than Spearman).

---

### fit_distribution

Fit statistical distributions to a numeric column and rank by KS-test p-value.

| Arg | Type | Required | Description |
|---|---|---|---|
| `column` | string | yes | Numeric column to fit |

**Candidates:** `normal`, `exponential`, `lognormal`, `gamma`, `weibull_min`.

**Returns:**
```json
{
  "best_fit": "lognormal",
  "fits": [
    {"distribution": "lognormal", "ks_statistic": 0.02, "p_value": 0.45, "params": {...}},
    {"distribution": "gamma", "ks_statistic": 0.04, "p_value": 0.12, "params": {...}},
    ...
  ]
}
```

Note: `fit_distribution` is defined in `stat_tools.py` but may not be registered in the default quant analyst registry. It is available when a custom tool registry is used.

---

### run_python

Execute a Python snippet for custom statistical analysis. Sandboxed with restricted imports and timeout enforcement.

| Arg | Type | Required | Description |
|---|---|---|---|
| `code` | string | yes | Python code to execute; `print()` output is captured and returned |

**Returns:**
```json
{"output": "printed output here..."}
```
Or on error:
```json
{"error": "NameError: name 'foo' is not defined"}
```

**Pre-loaded globals:**
- `np` (numpy)
- `pd` (pandas)
- `stats` (scipy.stats)
- `math`, `json`, `itertools`, `collections`, `functools`, `datetime`, `re`
- `df` (analyst results as a pandas DataFrame)

**Import whitelist:** Only standard-library and scientific modules are importable: `numpy`, `pandas`, `scipy`, `math`, `json`, `itertools`, `collections`, `functools`, `datetime`, `re`, `statistics`, `warnings`, `operator`, `string`, `textwrap`, `decimal`, `fractions`, `numbers`, `copy`, `enum`, `typing`, `io`, `csv`, `dataclasses`, `abc`.

System modules (`os`, `subprocess`, `sys`, `socket`, etc.) are blocked.

**Timeout:** 10 seconds (configurable via `PYTHON_EXEC_TIMEOUT_SECONDS`). Enforced via `SIGALRM` on Unix (silently skipped on Windows or non-main threads).

**DataFrame sync-back:** If the code modifies `df`, the modified DataFrame is written back to `context.analyst_results` so subsequent tools see derived columns.

---

## 4. Advanced Tools

These tools are defined in `vendored/agents_core/advanced_tools.py` and selectively registered by agents that need them.

### Time-Series Tools

#### compute_time_series_slope

Fit linear regression (scipy.stats.linregress) to a metric over a time/ordinal index.

| Arg | Type | Required | Description |
|---|---|---|---|
| `value_column` | string | yes | Numeric column to fit regression on (y-axis) |
| `time_column` | string | optional | Column to use as x-axis; uses row index if omitted |
| `time_unit` | enum | optional | Label: `day`, `week`, `month` (interpretation text only) |

**Returns:** `slope`, `intercept`, `r_squared`, `p_value`, `std_error`, `ci_95`, `trend_direction` ("increasing"/"decreasing"/"stable"), `interpretation`

---

#### compute_area_under_curve

Compute the area under a time-series curve using `numpy.trapz` -- useful for cumulative impact metrics.

| Arg | Type | Required | Description |
|---|---|---|---|
| `value_column` | string | yes | Numeric column (y-values) |
| `time_column` | string | optional | Numeric time column for non-uniform x-axis |

**Returns:** `auc`, `n_points`, `sum`, `mean`, `interpretation`

---

#### compute_percentage_change

Compute period-over-period percentage change in a metric series, plus momentum (accelerating vs. decelerating).

| Arg | Type | Required | Description |
|---|---|---|---|
| `value_column` | string | yes | Numeric column |
| `time_column` | string | optional | For row ordering only (values not used numerically) |
| `lag` | int | optional | Number of periods to lag (default 1) |

**Returns:** `n_periods`, `lag`, `mean_pct_change`, `std_pct_change`, `min_pct_change`, `max_pct_change`, `periods_positive`, `periods_negative`, `momentum_direction`, `interpretation`

---

#### detect_peaks

Detect local peaks (surge periods) in a numeric series using `scipy.signal.find_peaks`.

| Arg | Type | Required | Description |
|---|---|---|---|
| `value_column` | string | yes | Numeric column |
| `time_column` | string | optional | Label column for peak positions |
| `num_peaks` | int | optional | Max peaks to return (default 5) |
| `min_prominence_ratio` | float | optional | Minimum prominence as fraction of value range (0-1, default 0.2) |

**Returns:** `n_peaks_found`, `top_peaks` (array with index, label, value, surrounding_avg, deviation_from_avg_pct), `interpretation`

---

#### detect_change_points

Detect structural change points using variance-minimization, validated with an unpaired t-test.

| Arg | Type | Required | Description |
|---|---|---|---|
| `value_column` | string | yes | Numeric column |
| `time_column` | string | optional | Label column for change-point positions |
| `min_segment_size` | int | optional | Minimum rows per segment (default 5) |

**Returns:** `n_changepoints`, `changepoints` (array with mean_before, mean_after, pct_change, t_stat, p_value, significant), `interpretation`

---

### Fraud and Risk Tools

Note: These tools were originally designed for financial transaction analysis. The names reference "fraud" but the statistical methods are general-purpose and applicable to any binary classification problem (churn, conversion, defects, etc.).

#### score_fraud_risk

Compute empirical risk lift for multi-dimensional segments. Lift = segment_rate / overall_rate. Also computes chi-squared contribution per segment.

| Arg | Type | Required | Description |
|---|---|---|---|
| `group_columns` | string[] | yes | Categorical columns to segment by |
| `fraud_column` | string | optional | Binary flag column (0/1). Default: `fraud_flag` |
| `min_segment_size` | int | optional | Minimum rows per segment (default 10) |
| `top_n` | int | optional | Return top-N highest-risk segments (default 10) |

**Returns:** `overall_rate`, `high_risk_segments` (array with rate, lift, chi2_contribution), `interpretation`

---

#### detect_amount_anomalies

Detect anomalous values using the Modified Z-score method (Iglewicz & Hoaglin 1993): `M_i = 0.6745*(x_i - median) / MAD`. More robust than mean/std for fat-tailed distributions.

| Arg | Type | Required | Description |
|---|---|---|---|
| `amount_column` | string | optional | Numeric column (default: `amount_inr`) |
| `group_by` | string | optional | Categorical column for per-group anomaly detection |
| `z_threshold` | float | optional | Modified Z-score threshold (default 3.5) |

**Returns:** `method`, `z_threshold`, anomaly stats (group_size, anomaly_count, anomaly_rate, median, MAD, min/max anomaly values). When `group_by` is provided, returns `results_by_group` array.

---

#### test_temporal_fraud_clustering

Test whether events are uniformly distributed across time periods using a chi-squared goodness-of-fit test. Shannon entropy measures concentration.

| Arg | Type | Required | Description |
|---|---|---|---|
| `time_column` | string | optional | Temporal column (default: `hour_of_day`) |
| `fraud_column` | string | optional | Binary flag column (default: `fraud_flag`) |
| `alpha` | float | optional | Significance level (default 0.05) |

**Returns:** `total_cases`, `n_periods`, `chi2_stat`, `p_value`, `significant`, `entropy`, `normalized_entropy`, `peak_periods` (top 5), `interpretation`

---

#### compute_bank_pair_risk

Compute risk for each sender-receiver pair with Z-tests against baseline and Bonferroni correction for multiple comparisons.

| Arg | Type | Required | Description |
|---|---|---|---|
| `sender_col` | string | optional | Sender column (default: `sender_bank`) |
| `receiver_col` | string | optional | Receiver column (default: `receiver_bank`) |
| `fraud_col` | string | optional | Binary flag column (default: `fraud_flag`) |
| `min_pair_size` | int | optional | Minimum transactions per pair (default 5) |
| `top_n` | int | optional | Return top-N riskiest pairs (default 5) |

**Returns:** `baseline_rate`, `n_pairs_evaluated`, `bonferroni_threshold`, `top_riskiest_pairs` (array with rate, lift, z_score, p_value, significant_after_bonferroni), `interpretation`

---

### General Analytics Tools

#### compute_percentile_rank

Rank segments by a numeric metric and assign quartile or decile buckets -- useful for benchmarking and performance tiering.

| Arg | Type | Required | Description |
|---|---|---|---|
| `metric_column` | string | yes | Numeric column to rank |
| `group_column` | string | yes | Categorical column for segments |
| `n_bins` | enum | optional | `4` (quartile, default) or `10` (decile) |

**Returns:** `ranked_segments` (array with group, value, rank, percentile, bucket_label), `interpretation`

---

#### compute_concentration_index

Compute the Herfindahl-Hirschman Index (HHI = sum(share_i^2) * 10000). Classification: 0-1500 = competitive, 1500-2500 = moderate concentration, >2500 = highly concentrated.

| Arg | Type | Required | Description |
|---|---|---|---|
| `group_column` | string | yes | Categorical column |
| `value_column` | string | optional | Numeric weight column; uses row counts if absent |

**Returns:** `hhi`, `interpretation`, `top_3_share_pct`, `n_segments`, `segments` (array with share_pct)

---

#### test_benford_law

Test whether numeric values conform to Benford's law (expected first-digit distribution: P(d) = log10(1 + 1/d)). Significant deviation may indicate data quality issues or synthetic generation artifacts. Requires >= 100 data points.

| Arg | Type | Required | Description |
|---|---|---|---|
| `amount_column` | string | optional | Numeric column (default: `amount_inr`) |

**Returns:** `n_valid`, `chi2_stat`, `p_value`, `significant`, `digit_distribution` (array with observed_pct, expected_pct, deviation), `interpretation`

---

## 5. Tool Safety

### Read-Only SQL Enforcement (D-053 Dual Enforcement)

Every SQL execution goes through **two independent enforcement layers:**

**Layer 1: Regex blocklist** (`sql_guard.py`)
```python
FORBIDDEN_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)
```
Applied in the `run_sql` tool before execution. Blocked queries return an error.

**Layer 2: Connection-level enforcement** (`connector.py`)
- SQLite: `PRAGMA query_only = ON` set before query, reset in `finally`.
- Postgres: Read-only connection with `default_transaction_read_only=True`.

Any attempt to write while read-only is enforced raises a database-level error. Both layers must fail for a write to succeed -- hence "belt and suspenders."

### Error Sanitization

`ToolRegistry.execute()` wraps every tool call:

```python
async def execute(self, name, args, context):
    try:
        return await tool.execute(context, args)
    except Exception as e:
        return json.dumps({"error": str(e)})
```

Python tracebacks are never sent to the LLM or user. Only the exception message string. The LLM receives clean error strings and can adjust its next tool call based on the error content (e.g., _"column 'amounts' does not exist" → the LLM tries `amount` instead).

### Row Limits

All SQL execution uses `fetchmany(limit)` instead of `fetchall()`. The limit is configured via `SQL_ROW_LIMIT` (default 1000). This prevents accidental full-table scans from overwhelming memory.

### Timeouts

- SQL execution: `SQL_TIMEOUT_SECONDS` (default 30s). Enforced via `statement_timeout` (Postgres) or `connect_timeout` (SQLite).
- Python execution: `PYTHON_EXEC_TIMEOUT_SECONDS` (default 10s). Enforced via `SIGALRM` on Unix.

### Table Access Control

The `allowed_tables` field in `ToolContext` restricts which tables the `run_sql` tool can query. The `validate_tables(sql, allowed)` function in `sql_guard.py` checks that all referenced tables are in the allowed set.

### Agent Iteration Limits

- Analyst: `max_agent_iterations` (default 25) -- prevents infinite tool-calling loops.
- Quant analyst: `max_quant_analyst_iterations` (default 5).
- Orchestrator tasks: `max_orchestrator_tasks` (default 10).

---

## 6. Adding New Tools

### Step 1: Implement the Tool

Create a class that extends `Tool` (ABC):

```python
from vendored.agents_core.tool_base import Tool, ToolContext

class MyNewTool(Tool):
    @property
    def name(self) -> str:
        return "my_new_tool"

    @property
    def description(self) -> str:
        return "What this tool does, when to use it, and what it returns."

    def get_args_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "..."},
            },
            "required": ["param1"],
        }

    async def execute(self, context: ToolContext, args: dict) -> str:
        # Do work here
        result = do_something(args["param1"], context)
        return json.dumps({"result": result})
```

### Step 2: Register the Tool

Add your tool to the appropriate registry factory:

```python
def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(RunSqlTool())
    registry.register(GetSchemaTool())
    registry.register(SearchSimilarTool())
    registry.register(MyNewTool())  # <-- Add here
    return registry
```

### Step 3: Update Prompts (if needed)

If your tool changes the agent's available capabilities, update the system prompt (`.j2` template) to describe when and how the LLM should use the new tool.

### Tool Contract Checklist

When implementing a tool, ensure:
- [ ] `name` is a lowercase snake_case string.
- [ ] `description` explains what the tool does, when to use it, and what it returns (the LLM uses this to decide whether to call the tool).
- [ ] `get_args_schema()` returns a valid JSON Schema object with `type: "object"` at root.
- [ ] `execute()` always returns a JSON string (never raises).
- [ ] Errors are returned as `{"error": "description"}` JSON, not raised.
- [ ] The tool is safe -- no filesystem access, no network access, no unbounded resource consumption.
- [ ] Any database access goes through the `context.db` connector (which enforces read-only and row limits).

---

## 7. RAG System

The RAG (Retrieval-Augmented Generation) system provides semantic search over past queries, schema DDL, and documentation.

### Backend: pgvector

RAG uses **pgvector** (Postgres extension), not ChromaDB. The `VectorStoreBackend` Protocol in `vendored/agents_core/rag/base.py` defines the interface, and `rag/pgvector_store.py` implements it against Postgres.

**Protocol methods:**
```python
class VectorStoreBackend(Protocol):
    def add_qa_pair(question, sql, metadata=None) -> str: ...
    def add_ddl(ddl, table_name="") -> str: ...
    def add_documentation(doc, metadata=None) -> str: ...
    def search_qa(question, n=5, max_distance=None, sql_valid_only=False) -> list[dict]: ...
    def search_ddl(question, n=3) -> list[dict]: ...
    def search_docs(question, n=3) -> list[dict]: ...
    # ... plus delete and management methods
```

### Collections
- **qa_pairs**: Question-to-SQL pairs from training data and auto-save.
- **ddl**: CREATE TABLE statements.
- **docs**: Business documentation strings.
- **findings**: Reserved for anomaly detection results (currently unused).
- **column_metadata**: Column descriptions and semantic metadata.

### Deduplication

Document IDs are deterministic: `SHA-256(content)[:16]`. This means inserting the same content twice is a no-op, making the trainer idempotent and safe to call on every startup.

### Training (Document RAG)

The trainer loads seed data from:
1. DDL from live database introspection.
2. Documentation from the database profile's column summaries and descriptions.
3. Example Q-SQL pairs from seed data or auto-saved from past successful answers.

### Schema Training

Column metadata is embedded and indexed for the SchemaLinker's semantic search signal. This allows the linker to find columns relevant to a question even when the question uses different terminology than the schema.
