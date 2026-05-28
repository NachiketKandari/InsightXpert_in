# Automations

Automations let you schedule SQL queries to run on a recurring basis against any database in your workspace. When the results meet conditions you define, you receive a notification.

---

## What Are Automations?

An automation is a **cron-driven pipeline** attached to a specific database. On each scheduled tick, it runs one or more SQL queries in sequence, evaluates trigger conditions against the results, and dispatches notifications via SSE when conditions fire.

Use cases:

- Monitor row counts against a threshold (e.g., "alert when daily signups drop below 50")
- Detect changes in key metrics from run to run
- Track trends across multiple executions (slope detection)
- Get notified when something unusual appears in your data

---

## Architecture

```
[EmbeddedScheduler tick] or [External cron webhook]
          |
          v
  claim_due_automations()  -- atomic claim with FOR UPDATE SKIP LOCKED
          |
          v
  _execute_one(automation_id)  -- per-automation asyncio.Lock re-entrancy guard
          |
          v
  Run SQL queries sequentially against target database
          |
          v
  TriggerEvaluator checks conditions against final query result
          |
          v
  Persist AutomationRun row + create Notification + dispatch via SSE
```

The scheduler can run in one of two modes depending on deployment topology.

### Scheduler Modes

**Embedded mode** (`AUTOMATIONS_SCHEDULER_MODE=embedded`, default):

- An APScheduler `AsyncIOScheduler` runs inside the FastAPI process.
- Ticks every `AUTOMATIONS_SCHEDULER_TICK_SECONDS` (default 30s).
- `max_instances=1`, `coalesce=True` -- if a prior tick is still running, the next one is skipped.
- Single-process friendly. Suitable for single-replica Cloud Run deployments.

**External mode** (`AUTOMATIONS_SCHEDULER_MODE=external`):

- No internal scheduler is started. The app process does no cron work.
- An external cron service (e.g., Cloud Scheduler) POSTs to `/api/internal/run-due-automations`.
- Requests are authenticated via HMAC-SHA256 (`X-Scheduler-Signature` header).
- Replay protection: max 5-minute drift on the `tick_at` payload field.
- Returns 503 if `AUTOMATIONS_ENABLED=false` or scheduler mode is not `"external"`.

### Multi-Replica Safety

Row claiming uses `FOR UPDATE SKIP LOCKED` (Postgres) or read-then-update with write-lock (SQLite). `next_run_at` is advanced past the due predicate atomically, preventing double-fire across replicas.

---

## Automation Lifecycle

1. **Create** -- User defines a name, target database, one or more SQL queries, a cron schedule, and optional trigger conditions.
2. **Schedule** -- The scheduler computes `next_run_at` from the cron expression and inserts the automation row.
3. **Trigger** -- At each tick, the scheduler claims all automations whose `next_run_at <= now`.
4. **Execute** -- SQL queries run sequentially against the target database. Each query returns at most 1000 rows.
5. **Store result** -- An `AutomationRun` row is persisted with status, result data, execution time, and any fired triggers.
6. **Notify** -- If trigger conditions fire, a `Notification` is created and dispatched to the owner via SSE.

---

## API Reference

All endpoints are under `/api/v1/automations`. Authentication is via session cookie (same as the rest of the app).

### Automation CRUD

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/automations` | Create a new automation. Per-user cap enforced atomically (default 429 on exceed). |
| `GET` | `/api/v1/automations` | List the current user's automations (paginated: `?limit=&offset=`). |
| `GET` | `/api/v1/automations/{id}` | Get a single automation with detail. |
| `PUT` | `/api/v1/automations/{id}` | Update name, queries, schedule, or trigger conditions. |
| `DELETE` | `/api/v1/automations/{id}` | Delete an automation and its associated runs. |
| `POST` | `/api/v1/automations/{id}/toggle` | Enable or disable (active/inactive). |
| `POST` | `/api/v1/automations/{id}/runs` | Run immediately (manual trigger). Returns run results. |
| `GET` | `/api/v1/automations/{id}/runs` | Run history (`?limit=`, default 20, max 100). |
| `GET` | `/api/v1/automations/{id}/runs/{run_id}` | Get a specific run's detail. |

### AI Assistance

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/automations/compile-trigger` | Compile natural language into a structured trigger condition. Accepts `{nl_text, available_columns}`. Returns compiled trigger JSON or a default fallback (`threshold > 0`). |
| `POST` | `/api/v1/automations/generate-sql` | Generate a SQL query from a natural language prompt. |

### Trigger Templates

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/automations/templates` | List trigger templates (paginated). |
| `POST` | `/api/v1/automations/templates` | Create a reusable trigger template. |
| `GET` | `/api/v1/automations/templates/{id}` | Get a template's detail. |
| `PUT` | `/api/v1/automations/templates/{id}` | Update a template. |
| `DELETE` | `/api/v1/automations/templates/{id}` | Delete a template. |

### Internal Endpoint

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/internal/run-due-automations` | HMAC-SHA256 | External cron webhook. Accepts `{tick_at: unix_seconds}`. |

### Notifications (`/api/v1/notifications`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/notifications` | List current user's notifications (`?unread=&limit=`). |
| `GET` | `/api/v1/notifications/all` | Admin-only: cross-user notification feed. |
| `GET` | `/api/v1/notifications/count` | Get unread count for the badge. |
| `GET` | `/api/v1/notifications/stream` | SSE stream for real-time notification delivery (15s ping interval). |
| `POST` | `/api/v1/notifications/{id}/read` | Mark a single notification as read. |
| `POST` | `/api/v1/notifications/mark-all-read` | Mark all of current user's notifications as read. |

---

## Cron Expressions

Automations use standard 5-field cron expressions:

| Field | Values | Allowed special chars |
|---|---|---|
| Minute | 0-59 | `, - * /` |
| Hour | 0-23 | `, - * /` |
| Day of month | 1-31 | `, - * /` |
| Month | 1-12 | `, - * /` |
| Day of week | 0-6 (0=Sunday) | `, - * /` |

### Built-in Presets

The schedule picker provides these presets out of the box:

| Preset | Cron | Description |
|---|---|---|
| Hourly | `0 * * * *` | Every hour at minute 0 |
| Daily | `0 9 * * *` | Every day at 9:00 AM |
| Weekly | `0 9 * * 1` | Every Monday at 9:00 AM |
| Monthly | `0 9 1 * *` | First day of each month at 9:00 AM |

Custom expressions of any valid 5-field cron are also supported.

---

## Trigger Conditions

Trigger conditions determine **when you get notified**. If you leave them empty, every scheduled run records a `success` status but no notification is created.

Each condition has a **type**:

| Type | What it checks |
|---|---|
| `threshold` | A numeric column in the result crosses a comparison value (`gt`, `gte`, `lt`, `lte`, `eq`, `ne`). |
| `row_count` | The number of rows returned meets a threshold. |
| `change_detection` | A column's value changed by N% compared to the **previous run**. Requires at least one prior run. |
| `column_expression` | A column value across rows meets a condition. Scope: `any_row` or `all_rows`. |
| `slope` | A numeric column's trend across recent runs, computed via linear regression over `slope_window` data points (default 5). Requires at least 2 data points (current + 1 previous run). |

**AI Trigger Compilation**: Describe the condition in plain English (e.g., "alert when daily transaction count drops below 500") and the system compiles it into a structured condition via `POST /api/v1/automations/compile-trigger`. The LLM is prompted to output a JSON condition matching one of the five types. If parsing or validation fails, it falls back to a `threshold > 0` default.

---

## Templates

Trigger condition sets can be saved as reusable templates. Templates are stored server-side with owner scoping.

| Action | Description |
|---|---|
| **Save as Template** | Save the current conditions under a name for reuse across automations. |
| **Load** | Select a saved template to populate the condition builder. |
| **Delete** | Remove a template. |

---

## Notification Integration

When trigger conditions fire, a `Notification` is created for the automation's owner. Notifications have a severity level:

| Severity | Use case |
|---|---|
| `info` | General information, e.g., "row count exceeded 100" |
| `warning` | Attention needed, e.g., "failure rate increased by 15%" |
| `critical` | Urgent alert, e.g., "fraud flag rate jumped to 45%" |

### Delivery

Notifications are delivered in two ways:

1. **SSE push** -- Real-time delivery via `GET /api/v1/notifications/stream`. The frontend subscribes on mount and receives notifications as they are created.
2. **Polling fallback** -- The notification bell in the header polls `GET /api/v1/notifications/count` every 30 seconds.

### Notification UI Components

| Component | File | Purpose |
|---|---|---|
| `NotificationBell` | `components/notifications/notification-bell.tsx` | Header bell icon with unread count badge |
| `NotificationPopover` | `components/notifications/notification-popover.tsx` | Dropdown showing recent unread notifications |
| `NotificationCard` | `components/notifications/notification-card.tsx` | Individual notification with type icon and severity |
| `NotificationDetailModal` | `components/notifications/notification-detail-modal.tsx` | Full notification content with linked run details |

### Notification Store (`notification-store.ts`)

Zustand store managing notification state with optimistic updates:

- `fetchNotifications(unreadOnly?)` -- fetch current user's notifications
- `fetchAllNotifications(unreadOnly?)` -- admin-scoped cross-user fetch
- `fetchUnreadCount()` -- fetch unread count for badge display
- `markAsRead(id)` -- optimistic mark-as-read with rollback on failure
- `markAllAsRead()` -- optimistic mark-all-as-read with rollback on failure

---

## Configuration

All automation behavior is controlled via environment variables in the backend:

| Variable | Default | Description |
|---|---|---|
| `AUTOMATIONS_ENABLED` | `false` | Master switch. When `false`, all automation routes return 503. |
| `AUTOMATIONS_SCHEDULER_MODE` | `embedded` | `embedded` for APScheduler in-process, `external` for webhook-driven. |
| `AUTOMATIONS_SCHEDULER_TICK_SECONDS` | `30` | Tick interval in embedded mode. How often the scheduler checks for due automations. |
| `AUTOMATIONS_MAX_PER_USER` | (server-side) | Max automations per user. Enforced atomically at creation time. |
| `AUTOMATIONS_HMAC_KEY` | (required in external mode) | Pre-shared key for HMAC-SHA256 signature verification of external webhook calls. |

### Gating

The frontend checks `GET /api/v1/client-config` on load. The `features.automations` flag controls whether automations UI is rendered. When `false`, the automations page and bell icons are hidden.

---

## Frontend

### Automations Page (`/automations`)

The dedicated automations page is at `/automations` (wrapped in `AuthGuard` layout). It shows:

- A list of all user automations with name, status (active/paused), schedule, and last run date.
- Each automation card expands to show the NL query, SQL queries, next run time, and run history.
- A **New Automation** button opens a form-based dialog for creating automations (name, database selector, SQL queries, cron schedule, trigger conditions).
- Card actions: toggle enable/disable, manual run, edit, delete.

### Key Components

| Component | File | Purpose |
|---|---|---|
| `AutomationsClient` | `app/automations/automations-client.tsx` | Top-level page with header, list, and new-automation dialog |
| `AutomationList` | `components/automations/automation-list.tsx` | Fetches and renders automation cards |
| `AutomationCard` | `components/automations/automation-card.tsx` | Expandable card with inline actions |
| `NewAutomationDialog` | `components/automations/new-automation-dialog.tsx` | Form-based create dialog |
| `SchedulePicker` | `components/automations/schedule-picker.tsx` | Preset + custom cron expression picker |
| `TriggerConditionBuilder` | `components/automations/trigger-condition-builder.tsx` | Form builder for trigger conditions |
| `ConditionRow` | `components/automations/condition-row.tsx` | Single condition row in the builder |
| `TriggerTemplatePicker` | `components/automations/trigger-template-picker.tsx` | Load/save trigger templates |
| `AiSqlGenerator` | `components/automations/ai-sql-generator.tsx` | NL-to-SQL generation component |
| `SqlEditorModal` | `components/automations/sql-editor-modal.tsx` | SQL editor with live execution against the database |
| `RunHistory` | `components/automations/run-history.tsx` | Chronological run log with expandable detail |
| `RunDetailModal` | `components/automations/run-detail-modal.tsx` | Detailed view of a single run |

### Automation Store (`automation-store.ts`)

Zustand store managing automation state:

- CRUD operations (create, fetch, update, delete, toggle).
- Manual run triggering with result tracking.
- Test trigger state: client-side interval that runs the automation repeatedly and tracks iteration count and live status.
- Trigger template management.

---

## SQL Validation

All SQL queries submitted through automations are validated before execution:

- **Read-only enforcement**: Only `SELECT`, `WITH`, and `EXPLAIN` statements are allowed. Write operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, etc.) are blocked via `FORBIDDEN_SQL_RE`.
- **No multi-statement**: Semicolons within SQL body are rejected.
- **Completeness check**: The SQL must parse as a complete statement.
- **Row limit**: Each query returns at most 1000 rows per execution.

---

## Data Model

```
automations
  id                    UUID PK
  name                  VARCHAR(255)
  db_id                 FK -> databases.db_id
  nl_query              TEXT (original natural language question)
  sql_queries_json      TEXT (JSON array of SQL strings)
  cron_expression       VARCHAR(100)
  is_active             BOOLEAN (default true)
  owner_user_id         FK -> users.id
  last_run_at           DATETIME
  next_run_at           DATETIME
  workflow_graph_json   TEXT (serialized workflow, nullable)
  created_at            DATETIME
  updated_at            DATETIME

automation_triggers
  id                    UUID PK
  automation_id         FK -> automations.id (CASCADE)
  ordinal_position      INTEGER
  type                  VARCHAR(50) -- threshold, row_count, change_detection, column_expression, slope
  column                VARCHAR(255)
  operator              VARCHAR(10) -- gt, gte, lt, lte, eq, ne
  value                 FLOAT
  change_percent        FLOAT
  scope                 VARCHAR(20) -- any_row, all_rows
  slope_window          INTEGER
  nl_text               TEXT
  created_at            DATETIME
  updated_at            DATETIME

automation_runs
  id                    UUID PK
  automation_id         FK -> automations.id (CASCADE)
  status                VARCHAR(20) -- success, no_trigger, error
  result_json           TEXT (JSON)
  row_count             INTEGER
  execution_time_ms     INTEGER
  triggers_fired_json   TEXT (JSON)
  error_message         TEXT
  created_at            DATETIME

notifications
  id                    UUID PK
  user_id               FK -> users.id (CASCADE)
  automation_id         FK -> automations.id (CASCADE)
  run_id                FK -> automation_runs.id (SET NULL)
  title                 VARCHAR(500)
  message               TEXT
  severity              VARCHAR(20) -- info, warning, critical
  is_read               BOOLEAN (default false)
  created_at            DATETIME

trigger_templates
  id                    UUID PK
  name                  VARCHAR(255)
  description           TEXT
  conditions_json       TEXT (JSON array of trigger conditions)
  owner_user_id         FK -> users.id (CASCADE)
  created_at            DATETIME
  updated_at            DATETIME
```

---

## Current Limitations

- SQL queries are read-only (`SELECT`/`WITH`/`EXPLAIN` only).
- Each SQL query in the chain returns a maximum of 1000 rows.
- The slope trigger requires at least 2 data points (current + 1 previous run).
- The change_detection trigger requires at least one prior run for comparison.
- In embedded mode, tick-based scheduling means there is up to `AUTOMATIONS_SCHEDULER_TICK_SECONDS` of jitter on execution times.
- Notifications are delivered via SSE push with polling fallback; there is no guaranteed delivery mechanism (no email, Slack, or webhook integrations).
- LLM token usage from automation runs is tracked in `query_metrics` with `source="automation"` but is not surfaced in the UI.
