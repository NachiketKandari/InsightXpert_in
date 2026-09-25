# Oracle DB Support — PRD (as built)

Status: **APPROVED + IMPLEMENTED** (mock-tested, no live Oracle available)
Date: 2026-09-25
Repo: `insightxpert.in` (BYO-DB "Connect a database" feature)

## 1. Decisions locked in from review

| Question | Answer |
|---|---|
| Scope | Oracle as a 4th tab in the existing Connect dialog (postgres / mysql / libsql today), **not** a `DATABASE_URL` swap |
| Import model | Live connection (whole DB), **not** a snapshot copy — "when we're taking in a db, we mean a db" |
| Table selection | Picker with **search + select-all/clear**, per-table **exact row counts**; selection saved as an allowlist |
| Row cap | Result sets capped at the existing default (**1000**, `settings.sql_row_limit`); **no cap on `COUNT(*)`** (single-row results are never truncated) |
| BLOB/RAW | Tables containing `BLOB`/`BFILE`/`RAW`/`LONG RAW` columns are **rejected in Phase 1** (disabled in picker + 400 on save) |
| Verification | **Mock-only tests** sufficient for merge; must not break existing functionality |
| Service name | `service_name` form (covers PDBs, XE, Autonomous DB). SID-only legacy DBs are out of scope |
| Schema | Optional `schema` field, defaults to the login user's own schema; system schemas (`SYS`, `SYSTEM`, `APEX_*`, …) refused |

## 2. What was built

### Backend (`apps/api`)

| File | Change |
|---|---|
| `pyproject.toml` / `uv.lock` | Added direct dep `oracledb>=2.0` (thin mode, no Instant Client) — same treatment as `psycopg`/`pymysql` |
| `connections/types.py` | `OracleConnection`: host, port=1521, service_name (required), schema (optional), username, password, `selected_tables: list[str] \| None`. `to_dsn()` → `oracle+oracledb://…`; password redaction inherited |
| `connections/oracle_connector.py` (new) | `OracleConnector` mirroring pg/mysql: `execute` (regex guard + `SET TRANSACTION READ ONLY` + rollback + `fetchmany(row_limit)`), `list_tables` (ALL_TABLES, 200 cap), `describe_table` (ALL_TAB_COLUMNS), `row_count` (exact COUNT(*), None on failure), `discovery_details` (one metadata query + per-table counts/unsupported flags), `dispose`. `UNSUPPORTED_COLUMN_TYPES = {BLOB, BFILE, RAW, LONG RAW}`, `is_system_schema()` |
| `db/dialects/oracle.py` (new) | `OracleAdapter`: `open_readonly` via oracledb DBAPI (lazy import, `call_timeout=30s`, best-effort read-only tx), `teardown_readonly` rollback, `is_timeout_error` (ORA-01013/timeout), Oracle profiling pack (`FETCH FIRST … ROWS ONLY`, `DBMS_RANDOM.VALUE`), `open_database`/`extract_schema` wired (not stubbed) |
| `db/dialects/oracle_database.py` (new) | `OracleDatabase` vendored-ABC wrapper (execute/close/context-manager + `conn` accessor) |
| `db/dialects/oracle_schema.py` (new) | `extract_oracle_schema`: tables/columns/PK/FK from `ALL_*` views → `DatabaseSchema`, filtered by `selected_tables` |
| `db/dialects/__init__.py` | Registered `oracle` (lazy import — registration never requires the driver) |
| `db/connector.py` | `resolve_connector` oracle branch; `DatabaseConnector.execute` enforces the saved table allowlist via `validate_tables` → `ForbiddenSQLError` (covers `/sql/execute`, automations, executor stage) |
| `services/database_service.py` | `DatabaseRef.selected_tables` + `owner`; `oracle` in non-sqlite kind query; refs built with selection + `effective_schema()`; `resolve_connector` oracle branch |
| `routes/connections.py` | `_build_typed_config` oracle; `/test` oracle returns `{ok, tables, details: {row_count, column_count, unsupported_columns}}`; `POST /connections` accepts `selected_tables` (oracle-only, else 400), re-validates subset + BLOB/RAW against live discovery before persisting (deviation from pg/mysql documented in code) |
| `databases/table.py` | kind CHECK + `'oracle'` (no alembic migration — same precedent as `'mysql'`, which also has none) |
| `shared_snapshots/service.py` + route | `oracle` added to `_DISALLOWED_KINDS`; refusal message updated |
| `prompts/sql_generation_oracle.j2` (new) | Oracle 19c rules: double-quoted identifiers, `FETCH FIRST`, `TO_CHAR`/`TRUNC`/`EXTRACT`, `\|\|` concat, `NVL`, DUAL — auto-picked via existing `prompt_variant` dispatch |
| `tests/test_oracle_support.py` (new) | 32 mock-only tests: types/DSN/redaction, helpers, dispatch, dialect registration, guardrails without network, discovery with fake engine, schema extractor with fake DBAPI, scope enforcement, registry refs, kind CHECK, share refusal, save-time validation |

### Frontend (`apps/web`)

| File | Change |
|---|---|
| `lib/connections/api.ts` | `ConnectionKind` + `"oracle"`, `OracleConfig`, `selected_tables` on request, `details` on test response |
| `lib/connections/tables.ts` (new) + `tables.test.ts` | Pure picker helpers (filter/toggle/select-all/clear/unsupported/format) — 8 vitest tests |
| `components/dataset/connect-db-dialog.tsx` | 4th **Oracle** tab (host/port/service/schema/user/pass); table picker after test (search, select-all/clear over visible rows, exact row counts, BLOB/RAW rows disabled with reason); full-select saved as `null` (future-proof), partial as explicit allowlist; Save requires ≥1 selected table |
| `types/database.ts` | `DatabaseSource` + `"oracle"` (and `"mysql"`, which was missing) |
| `components/chat/chat-panel.tsx` | `dbKindHint` covers oracle (+mysql mapping fix) |
| `components/chat/share-dialog.tsx` | Live-DB share refusal notice extended to oracle (same testid, copy generalized) |
| `lib/share-api.ts` | 403 text match + `"oracle"` → `postgres_refused` |

## 3. Row-cap semantics (as requested)

- Query result fetching: `fetchmany(row_limit)`, default **1000** everywhere (`settings.sql_row_limit`) — same as postgres/mysql. Configurable to 10k via existing setting; no code change needed.
- Row **counts** (`COUNT(*)` in picker, stats): single-row results, never truncated — effectively **no cap**.
- Table discovery capped at **200 tables** (parity with pg/mysql).

## 4. Verification

- Backend: `tests/test_oracle_support.py` — **32 passed** (mock-only, no live Oracle).
- Full backend suite: **same 20 failures before and after** (all pre-existing — missing `Databases/_shared/*.sqlite` fixtures that CI downloads from a release; proven by stashed-baseline comparison). 708 passed.
- Frontend: `tsc --noEmit` clean; new vitest file **8 passed**; eslint on touched files shows only one **pre-existing** error (share-dialog `set-state-in-effect`, present on clean tree).
- Backend ruff: new files clean except style nits matching sibling files (repo-wide ruff debt, not gating in CI which runs pytest only).

## 5. Known limits / follow-ups

1. Live Oracle verification not done (no instance available) — test/save/query paths follow the proven pg/mysql shapes, but a real 19c+ check is recommended before announcing support.
2. `open_database`/`extract_schema` are implemented (unlike mysql's stubs), so profiling/chat light up; vendored `StatsCollector` has hardcoded `LIMIT 20` / `APPROX_COUNT_DISTINCT` / `CAST(x AS TEXT)` which degrade gracefully per-column on Oracle (counts work, samples/min-max may be empty). A dialect-aware stats pass is a possible follow-up.
3. SID-only connections, TCPS/wallet, and multi-schema single-connection introspection are out of scope.
4. `mysql` share-refusal gap noted (mysql not in `_DISALLOWED_KINDS`) — left unchanged intentionally; consider a separate fix.
5. No alembic migration for the kind CHECK (matches `mysql` precedent); environments whose `databases` schema was built from metadata get the constraint via `table.py`.
