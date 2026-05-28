# Databases

InsightXpert.ai supports three types of databases: **bundled samples** (curated SQLite datasets from the BIRD benchmark), **user uploads** (your own SQLite or CSV files), and **BYO connections** (connect your external Postgres database directly).

---

## Database Types

### Bundled Samples

Curated SQLite databases shipped with the application. These are BIRD-benchmark-derived datasets that serve as starter datasets for exploration and testing. All users can see and query bundled databases.

### User-Uploaded

Upload your own SQLite (`.db`, `.sqlite`) or CSV files. Uploaded databases are private by default -- only the owner and super admins can see them. CSV uploads go through automatic type inference and SQLite table creation.

### BYO External Connections

Connect your own Postgres database by providing a connection string. Credentials are encrypted at rest with Fernet symmetric encryption. All queries through BYO connections run in read-only mode -- write operations are blocked at the connector level with both a forbidden-SQL regex and `default_transaction_read_only=on`.

---

## Bundled Databases

The following BIRD-benchmark datasets are bundled with the application:

| Database ID | Contents |
|---|---|
| `california_schools` | California public schools and their performance metrics, funding, and demographics. |
| `toxicology` | Chemical compound toxicity data, molecular properties, and biological assay results. |
| `debit_card_specializing` | Debit card transaction data with customer, account, and merchant dimensions. |
| `formula_1` | Formula 1 racing data: drivers, constructors, circuits, races, lap times, and standings. |
| `european_football_2` | European football leagues: teams, players, matches, goals, and league tables. |
| `thrombosis_prediction` | Medical dataset for thrombosis risk prediction: patient demographics, lab results, and outcomes. |
| `student_club` | University student club membership, events, budgets, and attendance records. |
| `codebase_community` | Software project community data: contributors, commits, issues, and releases. |

Each bundled database includes a full schema (table structure), a profile with per-column statistics and summaries, and generated sample questions.

---

## Uploading Databases

### Supported Formats

| Format | Extension | Max size | Description |
|---|---|---|
| SQLite | `.db`, `.sqlite` | 50 MB | Pre-built SQLite database files with tables and data. |
| CSV | `.csv` | 50 MB | Comma-separated values files. Imported into a new SQLite table. |

### Upload Flow

1. **Select file** -- Use the upload dialog triggered from the dataset selector dropdown or the chat input toolbar.
2. **Validation** -- The server validates file extension, size, and (for SQLite) magic bytes.
3. **Processing** -- CSV files are parsed with pandas, columns are auto-typed, and a sanitized SQLite table is created. SQLite files are used directly.
4. **Registration** -- A database record is created in the `databases` table with the appropriate source tag (`"uploaded"`).
5. **Profiling** -- After upload, you are prompted to run profiling to generate column summaries, statistics, and sample questions.

### CSV Type Inference

CSV columns are automatically typed by pandas during import:

| pandas dtype | Inferred SQLite type |
|---|---|
| `bool` | `BOOLEAN` |
| `int*` | `INTEGER` |
| `float*` | `REAL` |
| `datetime64` | `DATETIME` |
| `object`/`string` (boolean-like pairs) | `BOOLEAN` |
| `object`/`string` (>=90% datetime parseable) | `DATETIME` |
| Everything else | `TEXT` |

### Column Name Sanitization

Raw CSV headers are converted to safe SQLite column names: lowercased, non-alphanumeric characters replaced with underscores, consecutive underscores collapsed, leading/trailing underscores stripped. Empty results default to `"col"`.

### Visibility

Uploaded databases are **private** by default. Only the uploader and super admins can see them. Visibility can be changed to `"shared"` (specific users) or `"public"` (all authenticated users) by an admin via `POST /api/v1/databases/{db_id}/visibility`.

---

## BYO External Connections

Connect your own Postgres database to query it with natural language. All connections are read-only -- InsightXpert.ai cannot modify your data.

### Connection Setup

1. Navigate to the **Connections** section or use the `+` menu in the chat toolbar.
2. Provide a **database ID** (lowercase alphanumeric, hyphens, underscores; 1-64 characters matching `^[a-z0-9][a-z0-9_\-]{0,63}$`).
3. Provide the **connection details**: host, port (default 5432), database name, username, and password.
4. Choose a **schema** to restrict query scope (pinned via `search_path`).
5. The server validates the connection with a test query and lists available tables.
6. Credentials are encrypted at rest with **Fernet** symmetric encryption (AES-128-CBC with HMAC-SHA256) and stored in the `connection_config_encrypted` column.

### Read-Only Enforcement

Double write protection is enforced at the Postgres connector level:

1. **SQL validation**: The `FORBIDDEN_SQL_RE` regex blocks `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, and other write operations.
2. **Connection-level**: `default_transaction_read_only=on` is set on every psycopg3 connection, providing a defense-in-depth layer that blocks writes even if the regex were somehow bypassed.
3. **Statement timeout**: A configurable `statement_timeout` prevents long-running queries from exhausting resources.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/connections/test` | Test a connection. Returns `{ok: true, tables[]}`. |
| `POST` | `/api/v1/connections` | Create a saved connection. Returns `{db_id}` (201). |
| `GET` | `/api/v1/connections` | List saved connections (no credential data in response). |
| `DELETE` | `/api/v1/connections/{db_id}` | Delete a connection and its associated database record. |

---

## Database Profiling

Profiling is the process of analyzing a database's schema and data to build a rich metadata layer that powers accurate natural language querying.

### What Profiling Does

Profiling runs in **7 stages**, each configurable:

| Stage | What it produces | Requires LLM? |
|---|---|---|
| **Schema** | Table names, column names, types, nullability. Queries `sqlite_master` or `information_schema`. | No |
| **Stats** | Per-column statistics: distinct count, null count, min/max, sample values, numeric ranges. | No |
| **Join Graph** | FK relationships: declared constraints, value-verified containment ratios, bridge FK discovery. | No |
| **Summaries** | Per-column: short summary (one sentence), long summary (paragraph), BIRD-enriched summary. | Yes |
| **Quirks** | Per-column quirks: special characters, type mismatches, semantic hints, symbolic values, enumeration labels. | Yes |
| **LSH** | Locality-sensitive hashing for literal value matching during schema linking. | No |
| **Vectors** | pgvector embeddings for semantic search during schema linking. | Yes |

### Cost-Gate Handshake

Because LLM-powered profiling stages cost tokens, the system uses a **two-phase cost-gate**:

1. **Estimate**: The server computes the number of columns, batch size (`PROFILING_BATCH_SIZE`, default 20), total LLM calls, and estimated duration.
2. **Confirm**: The client displays the estimate. The user confirms to proceed. Admins are exempt from per-user daily caps.

### Batched LLM Calls

Both summaries and quirks use batched LLM calls:

- **Summaries**: `BatchedSummaryGenerator` sends N columns per batch (default 20) in a single LLM call, rather than one call per column. This reduces token overhead and latency.
- **Quirks**: `BatchedQuirkDetector` uses the same pattern, starting with rule-based detection then calling the LLM per batch.
- **Partial response fallback**: If the LLM response is missing entries for some columns, the system falls back gracefully rather than failing the entire batch.

### SSE Streaming

Profiling progress is streamed to the frontend in real time via SSE. The client receives:

- `profile_stage_started` -- a new stage has begun.
- `profile_progress` -- batch progress within a stage (batch_index / batch_total).
- `profile_stage_completed` -- stage finished with duration and notes.
- `profile_done` -- all stages complete with summary counts.
- `profile_error` -- an error occurred.

### Cache

Profile results are cached via `ProfileCache`, a process-level LRU memo with per-key `asyncio.Lock` singleflight. This prevents concurrent profile requests for the same database from triggering duplicate LLM calls.

---

## Multi-Dialect Support

InsightXpert.ai supports both **SQLite** and **Postgres** query targets through a `DialectAdapter` Protocol.

### How It Works

The `DialectAdapter` Protocol provides four dispatch seams:

1. **Connector open**: `open_readonly(ref)` returns a DB-API 2 connection. SQLite uses `sqlite3.connect()`, Postgres uses `psycopg3.connect()`.
2. **Schema extraction**: `extract_schema(db, ref)` returns table/column metadata. SQLite queries `sqlite_master`, Postgres queries `information_schema`.
3. **Validator parse**: `sqlglot_dialect` tells `sqlglot.transpile()` which dialect to use for SQL validation.
4. **Prompt selection**: `prompt_variant` resolves the Jinja template variant. SQLite uses `sql_generation.j2`, Postgres uses `sql_generation_postgres.j2` (swapping `STRFTIME` to `TO_CHAR`, `CAST(x AS REAL)` to `x::numeric`, `SUBSTR` to `SUBSTRING`, adding `ILIKE`, and providing schema-qualification guidance).

Call sites **never branch on dialect**. Every dispatch point calls `adapter.method(...)` -- no `if/elif`.

### Adding a New Dialect

To add a third dialect (e.g., MySQL, BigQuery):

1. Create one file in `db/dialects/` implementing the `DialectAdapter` Protocol.
2. Import and register it in the `__init__.py` registry.
3. Create one `sql_generation_<variant>.j2` prompt template.

Zero changes to existing code. This is the Protocol strategy pattern in action.

---

## Sample Questions

Each database can have auto-generated sample questions that help users explore what the database can answer.

### How They Work

Sample questions are generated by a **7-stage pipeline**:

1. **Feature extraction** -- Deterministic `SchemaFeatures` vector: temporal columns, categorical columns, numeric metrics, geographic columns, relationships.
2. **Category selection** -- Adaptive 3-of-5 choice from `{Descriptive, Comparative, Temporal, Segmentation, Correlation}`. Always picks Descriptive.
3. **Few-shot retrieval** -- Per category, picks the best example from a curated BIRD benchmark question bank using Hamming distance over boolean feature vectors.
4. **Prompt build** -- Renders schema compactly with few-shot examples.
5. **LLM call** -- Single call with strict JSON mode. 30s timeout.
6. **Validation** -- Strict rules: exactly 3 categories, 3 questions each, ends with `?`, maximum 200 characters, no near-duplicates (Jaccard <= 0.6).
7. **Fallback** -- If validation fails, a deterministic template-based generator fills in with schema feature placeholders.

### Lazy Generation

Questions are generated on-demand, not at profile time. The frontend triggers generation by calling `POST /api/v1/databases/{db_id}/sample-questions/ensure` when a user selects a database. This is an **idempotent** endpoint -- if questions already exist for the database, it returns them immediately.

Concurrent generation is capped at `asyncio.Semaphore(5)` to prevent LLM call floods when many users switch databases simultaneously.

### Sample Questions Modal

The `SampleQuestionsModal` component (`components/sample-questions/`) displays categorized questions in a dialog. Clicking a question sends it to the chat immediately.

---

## API Reference

All endpoints are under `/api/v1/databases`.

### Core Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/databases` | List databases visible to the current user. Returns `[{db_id, source, has_profile, table_count, column_count, row_count}]`. |
| `POST` | `/api/v1/databases/upload` | Upload a SQLite file (multipart, max 50 MB). Validates magic bytes. |
| `POST` | `/api/v1/databases/upload-csv` | Upload a CSV file (multipart, max 50 MB). Auto-typed and loaded into SQLite. |
| `GET` | `/api/v1/databases/{db_id}/schema` | Get the DDL and table list for a database. |
| `GET` | `/api/v1/databases/{db_id}/profile` | Get the cached profile (all 7 stages). Includes optional `sample_questions`. |
| `POST` | `/api/v1/databases/{db_id}/profile` | Run or re-run profiling. Accepts `{with_summaries?, with_quirks?, with_lsh?, with_vectors?, confirmed?}`. Returns SSE stream. |
| `POST` | `/api/v1/databases/{db_id}/visibility` | Admin-only: set visibility (`private`, `shared`, `public`) and share list. |
| `POST` | `/api/v1/databases/{db_id}/sample-questions/ensure` | Idempotent lazy sample question generation. Handles `pending` status guard. |
| `POST` | `/api/v1/databases/{db_id}/sample-questions/regenerate` | Force regeneration of sample questions. Returns 202. |

### SQL Execution

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/sql/execute` | Execute a read-only SQL query against a database. Accepts `{db_id, sql}`. Returns `{columns[], rows[][], row_count, execution_time_ms}`. |

### Admin Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/admin/databases` | Admin-enriched database list with owner email and share details. |
| `PATCH` | `/api/v1/admin/databases/{db_id}` | Set `pipeline_mode_default` (`"linked"` or `"full_schema"`). |

### Profile Override Endpoints

Profile values can be edited to correct or augment LLM-generated metadata:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/databases/{db_id}/profile/overrides` | List all overrides for a database. |
| `PUT` | `/api/v1/databases/{db_id}/profile/overrides` | Upsert an override (`{table_name, column_name, field_path, value_json}`). |
| `DELETE` | `/api/v1/databases/{db_id}/profile/overrides/{override_id}` | Delete an override. |

---

## Frontend Components

### Database Selector

The `DatasetSelector` (`components/layout/dataset-selector.tsx`) lives in the header. It shows a dropdown of all databases visible to the current user with:

- A checkmark on the currently selected database.
- Source badges (`bundled` / `uploaded` / `connection`).
- Profile status indicators (has_profile).
- Upload and connection actions.

### Database Card

`DatabaseCard` (`components/databases/database-card.tsx`) renders each database as a card with:

- Database name, source badge, row/table/column counts.
- **Profile** button (opens the profiling cost-gate dialog).
- **Schema** button (opens the schema panel).
- **Questions** button (triggers sample question generation).
- Visibility badge for non-private databases.

### Profiling UI

The profiling UI consists of:

| Component | File | Purpose |
|---|---|---|
| `CostConfirmModal` | `components/databases/cost-confirm-modal.tsx` | Shows estimated LLM calls and cost before profiling begins. |
| `ProfileStepper` | `components/databases/profile-stepper.tsx` | 7-stage progress display with live SSE updates. |
| `ProfileStepRow` | `components/databases/profile-step-row.tsx` | Individual stage row with status (pending/running/done/error). |
| `StageCheckboxGroup` | `components/databases/stage-checkbox-group.tsx` | Toggle which profiling stages to run. |
| `SchemaPanel` | `components/databases/schema-panel.tsx` | Browse tables, columns, and join graph results. |
| `AutoDisableWarning` | `components/databases/auto-disable-warning.tsx` | Warning when column count exceeds `PROFILING_MAX_COLUMNS_FOR_LLM` (500). |

### Database Detail Page

`/databases/{id}` provides a full detail view of a single database with:

- All tables and their column profiles (type, stats, summaries, quirks).
- Join graph visualization.
- Sample questions.
- Profile re-run controls.
- Profile override editor.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MAX_UPLOAD_MB` | `50` | Maximum file size for database uploads (SQLite and CSV). |
| `PROFILING_BATCH_SIZE` | `20` | Number of columns per LLM call for summaries and quirks. |
| `PROFILING_MAX_COLUMNS_FOR_LLM` | `500` | Threshold above which LLM-powered stages auto-disable with warning. |
| `CREDENTIAL_ENCRYPTION_KEY` | (required for BYO) | Fernet key for encrypting connection credentials at rest. Generate with `cryptography.fernet.Fernet.generate_key()`. |
| `GCS_BUCKET` | (optional) | Google Cloud Storage bucket for persisting uploaded database files. Falls back to local filesystem storage. |

---

## Current Limitations

- Uploaded SQLite databases must have valid SQLite magic bytes (validated on the first chunk).
- CSV uploads load the entire file into memory via pandas. At the 50 MB limit, the DataFrame can expand 3-5x in memory.
- BYO connections support Postgres only. MySQL, BigQuery, and other dialects require new DialectAdapter implementations.
- `information_schema` queries on large Postgres schemas may be slower than `sqlite_master` queries.
- Profile edits (overrides) are per-field and do not cascade to dependent stages (e.g., changing a column type does not re-run summaries).
- Sample questions use a Semaphore(5) concurrency cap -- generation for the 6th concurrent database request will queue.
