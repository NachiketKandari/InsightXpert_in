# InsightXpert.ai REST API Reference

**Base URL:** `http://localhost:8080` (dev) or your Cloud Run service URL (prod).
All endpoints are prefixed with `/api/v1/` unless explicitly noted otherwise.

## Authentication

InsightXpert.ai uses **itsdangerous HMAC-signed session cookies**, not JWT.

| Mechanism | Where used | How it works |
|---|---|---|
| `ix_session` HttpOnly cookie | All regular API calls | Set on login. Signed via `itsdangerous.URLSafeTimedSerializer` with a server-side `SESSION_SECRET`. HttpOnly, SameSite=Lax, Secure in non-local environments. |
| `Authorization: Bearer <token>` header | SSE streaming (`POST /api/v1/chat`) and WebSocket (`/api/transcribe`) | Fallback for clients that cannot send cookies (e.g., SSE calls bypassing the CDN proxy). The token value is the same signed session string. |

The `get_current_user` dependency checks the `ix_session` cookie first, then falls back to the `Authorization: Bearer` header. Both are validated by the same `SessionSigner.verify()` method.

**Session details:**
- TTL: 30 days sliding (`SESSION_TTL_SECONDS`, default 2592000)
- Cookie name: `ix_session` (configurable via `SESSION_COOKIE_NAME`)
- Invalidation: set `sessions_valid_after` on the user row to invalidate all prior sessions
- Password hashing: Argon2id (via `argon2-cffi`)

### Error Response Shape

All error responses share a consistent JSON body:

```json
{"detail": "Human-readable error message"}
```

Status codes: 400 (bad request), 401 (unauthorized), 403 (forbidden), 404 (not found), 409 (conflict), 422 (validation error), 429 (rate limit), 500/502/503 (server errors).

---

## 1. Auth Endpoints

Prefix: `/api/v1/auth`

### POST `/auth/login`

Authenticate an existing user. Sets the `ix_session` cookie on success.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "mysecretpassword"
}
```

**Response** `200 OK`:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "role": "user",
  "must_change_password": false
}
```

Sets `Set-Cookie: ix_session=<signed-token>; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000`.

**Errors:**
- `401 Unauthorized` -- invalid email or password

```bash
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@insightxpert.ai","password":"admin123"}' \
  -c cookies.txt
```

---

### POST `/auth/logout`

Invalidate the session by clearing the `ix_session` cookie.

**Response** `200 OK`:
```json
{"status": "ok"}
```

```bash
curl -X POST http://localhost:8080/api/v1/auth/logout -b cookies.txt
```

---

### GET `/auth/me`

Return the currently authenticated user.

**Response** `200 OK`:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "role": "user",
  "is_active": true,
  "must_change_password": false
}
```

**Errors:**
- `401 Unauthorized` -- no valid session

```bash
curl http://localhost:8080/api/v1/auth/me -b cookies.txt
```

---

### POST `/auth/change-password`

Change the authenticated user's password. Requires the current password.

**Request body:**
```json
{
  "current_password": "oldpassword",
  "new_password": "newsecurepassword"
}
```

**Response** `200 OK`:
```json
{"status": "ok"}
```

**Errors:**
- `401 Unauthorized` -- current password is incorrect

---

## 2. Chat Endpoints

### POST `/chat` -- Streaming SSE

Stream an AI-generated response to a natural-language question via Server-Sent Events. This is the primary chat endpoint.

**Auth:** Session cookie or Bearer header.

**Request body (`ChatRequest`):**
```json
{
  "message": "What are the top 5 merchant categories by transaction volume?",
  "db_id": "my_database",
  "conversation_id": null,
  "agent_mode": "auto",
  "pipeline_mode": null
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | `string` | Yes | The user's question (1--4096 chars) |
| `db_id` | `string` | Yes | Database identifier (1--128 chars) |
| `conversation_id` | `string` | No | Continue an existing conversation, or `null` to start a new one |
| `agent_mode` | `"basic"` \| `"agentic"` \| `"auto"` \| `null` | No | Analysis mode. `"auto"` pre-classifies the question. Default: `"auto"` |
| `pipeline_mode` | `"linked"` \| `"full_schema"` | No | Schema linking mode. `"full_schema"` is admin-only. Default: per-DB setting or `"linked"` |

**Response:** `text/event-stream`

**SSE Chunk envelope:**
```json
{"type": "<ChunkType>", "data": {...}, "conversation_id": "...", "timestamp": 1234567890.0}
```

**Typical chunk sequence for a successful pipeline turn:**
```
auto_routed (optional) -> few_shot_retrieved (optional) -> status -> profile_loaded ->
schema_linking_started -> candidate_sqls_generated -> literals_extracted -> semantic_matches ->
join_paths_added -> linked_schema_final -> sql_generated -> sql_executing -> rows_returned ->
answer_delta (multiple) -> answer_generated -> metrics -> [DONE]
```

**Error behavior:** If any error chunk is emitted, `answer` is skipped and the stream terminates with `[DONE]`.

```bash
curl -X POST http://localhost:8080/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message":"How many tables are there?","db_id":"my_db"}' \
  --no-buffer
```

---

### POST `/chat/poll` -- Batch Drain

Non-streaming version of `/api/v1/chat`. Runs the full pipeline to completion and returns all chunks at once. Schedules `record_turn` + `record_conversation_snapshot` as background tasks.

**Request body:** Same as `POST /api/v1/chat`.

**Response** `200 OK`:
```json
{
  "conversation_id": "abc123",
  "chunks": [
    {"type": "status", "data": {...}, "conversation_id": "abc123", "timestamp": 1700000000.0},
    {"type": "sql_generated", "data": {...}, "conversation_id": "abc123", "timestamp": 1700000001.0},
    {"type": "answer_generated", "data": {...}, "conversation_id": "abc123", "timestamp": 1700000002.0}
  ]
}
```

---

### POST `/chat/answer` -- Final Answer Only

Run the full pipeline and return only the final answer, conversation ID, and SQL queries. Returns 500 if any error chunk was emitted during processing.

**Request body:** Same as `POST /api/v1/chat`.

**Response** `200 OK`:
```json
{
  "conversation_id": "abc123",
  "answer": "The top 5 merchant categories by total transaction value are...",
  "sql": [
    "SELECT merchant_category, SUM(amount) AS total FROM transactions GROUP BY merchant_category ORDER BY total DESC LIMIT 5"
  ]
}
```

---

### POST `/chat/route` -- Mode Pre-Classifier

Classify a question as `"basic"` or `"agentic"` without running the full pipeline. Used by the frontend to show the routing decision before initiating chat.

**Request body:**
```json
{
  "question": "What is the monthly revenue trend over the last year?",
  "db_id": "my_db"
}
```

**Response** `200 OK`:
```json
{
  "mode": "agentic",
  "reason": "Requires multi-step analysis across time periods"
}
```

Uses `gemini-2.5-flash` with temperature=0.0, max 128 tokens, strict JSON mode. The server re-classifies as defense-in-depth when the actual `/chat` call is made.

---

## 3. Conversation Endpoints

Prefix: `/api/v1/conversations`

### GET `/conversations`

List all conversations for the current user, ordered by `updated_at DESC, created_at DESC`.

**Response** `200 OK`:
```json
[
  {
    "id": "abc123",
    "conversation_id": "abc123",
    "title": "Top merchant categories by volume",
    "starred": false,
    "db_id": "my_db",
    "created_at": "2026-05-20T10:30:00",
    "updated_at": "2026-05-20T10:32:00",
    "messages": []
  }
]
```

```bash
curl http://localhost:8080/api/v1/conversations -b cookies.txt
```

---

### GET `/conversations/search?q={keyword}`

Search conversations by title (ILIKE). Returns nothing if `q` is shorter than 2 characters.

**Query parameters:**
- `q` -- Search keyword (minimum 2 characters)

**Response** `200 OK` -- array of conversation objects matching the search.

---

### GET `/conversations/{conversation_id}`

Get full conversation detail with all messages and flat chunks.

**Response** `200 OK`:
```json
{
  "id": "abc123",
  "conversation_id": "abc123",
  "title": "Top merchant categories by volume",
  "starred": false,
  "db_id": "my_db",
  "created_at": "2026-05-20T10:30:00",
  "updated_at": "2026-05-20T10:32:00",
  "messages": [
    {
      "id": "msg001",
      "role": "user",
      "content": "What are the top 5 merchant categories?",
      "chunks": null,
      "feedback": null,
      "feedback_comment": null,
      "created_at": "2026-05-20T10:30:00"
    },
    {
      "id": "msg002",
      "role": "assistant",
      "content": "The top 5 merchant categories are...",
      "chunks": [
        {"type": "sql_generated", "data": {...}, "conversation_id": "abc123", "timestamp": 1700000001.0},
        {"type": "answer_generated", "data": {...}, "conversation_id": "abc123", "timestamp": 1700000002.0}
      ],
      "feedback": null,
      "feedback_comment": null,
      "created_at": "2026-05-20T10:30:05"
    }
  ]
}
```

`feedback` is `true` (thumbs up), `false` (thumbs down), or `null` (no feedback).

**Errors:**
- `404 Not Found` -- conversation not found or belongs to another user

---

### PATCH `/conversations/{conversation_id}`

Update conversation metadata.

**Request body:**
```json
{
  "title": "New conversation title",
  "starred": true
}
```

**Response** `200 OK` -- updated conversation object.

---

### DELETE `/conversations/{conversation_id}`

Delete a conversation and all its messages.

**Response:** `204 No Content`

**Errors:**
- `404 Not Found`

```bash
curl -X DELETE http://localhost:8080/api/v1/conversations/abc123 -b cookies.txt
```

---

## 4. Database Endpoints

Prefix: `/api/v1/databases`

### GET `/databases`

List all databases visible to the current user.

**Response** `200 OK`:
```json
[
  {
    "db_id": "my_db",
    "source": "upload",
    "has_profile": true,
    "table_count": 5,
    "column_count": 32,
    "row_count": 250000
  }
]
```

```bash
curl http://localhost:8080/api/v1/databases -b cookies.txt
```

---

### POST `/databases/upload`

Upload a SQLite database file.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `db_id` | `string` | Yes | Database identifier |
| `file` | `file` | Yes | SQLite database file |

**Response** `201 Created`:
```json
{
  "db_id": "my_db",
  "source": "upload"
}
```

**Upload guards:**
- SQLite magic byte validation on the first chunk
- Size cap enforcement (default 50 MB via `MAX_UPLOAD_MB`, returns 413 on oversize)
- Collision check (ownership) before reading the body
- Chunked read for memory safety

**Errors:**
- `409 Conflict` -- `db_id` already exists and is owned by another user
- `413 Payload Too Large` -- file exceeds `MAX_UPLOAD_MB`
- `400 Bad Request` -- not a valid SQLite file

---

### POST `/databases/upload-csv`

Upload a CSV file to create a new database table.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `db_id` | `string` | Yes | Database identifier |
| `file` | `file` | Yes | CSV file |

**Response** `201 Created`:
```json
{
  "db_id": "my_csv_db",
  "source": "csv"
}
```

CSV processing: pandas type inference (integer/real/text/datetime), sanitized column names, 500-row batch insert.

---

### GET `/databases/{db_id}/schema`

Return the DDL and table list for a database.

**Response** `200 OK`:
```json
{
  "ddl": "CREATE TABLE transactions (\n  transaction_id TEXT PRIMARY KEY,\n  ...\n)",
  "tables": ["transactions"]
}
```

---

### GET `/databases/{db_id}/profile`

Return the profiling results for a database, including optional `sample_questions`.

**Response** `200 OK` -- profile JSON object with column summaries, quirks, join paths, and sample questions.

---

### POST `/databases/{db_id}/profile`

Trigger profiling for a database. Returns SSE stream with profiling progress.

**Request body:**
```json
{
  "with_summaries": true,
  "with_quirks": true,
  "with_lsh": true,
  "with_vectors": true,
  "confirmed": false
}
```

**Response:** `text/event-stream` with profiling progress chunks. If expensive flags are set and `confirmed=false`, emits a single `profile_cost_estimate` chunk and waits for re-submission with `confirmed=true`.

**Rate limiting:** Per-user daily cap of `PROFILE_MAX_PER_USER_PER_DAY` (default 10). Returns 429 when exceeded. Admins are exempt.

---

### POST `/databases/{db_id}/sample-questions/regenerate`

Trigger asynchronous regeneration of sample questions for a database.

**Response** `202 Accepted`:
```json
{"status": "regenerating"}
```

---

### POST `/databases/{db_id}/visibility`

Admin-only. Set database visibility and sharing permissions.

**Request body:**
```json
{
  "visibility": "shared",
  "shared_with": ["user-id-1", "user-id-2"]
}
```

**Response** `200 OK`:
```json
{"status": "ok"}
```

---

## 5. Connections Endpoints (BYO DB)

Prefix: `/api/v1/connections`

Bring-your-own external database support. Credentials are encrypted at rest with Fernet symmetric encryption.

### GET `/connections`

List all connections for the current user. Credential config is not returned.

**Response** `200 OK`:
```json
[
  {
    "db_id": "my_postgres",
    "kind": "postgres",
    "created_at": "2026-05-20T10:00:00"
  }
]
```

---

### POST `/connections`

Create a new external database connection.

**Request body:**
```json
{
  "db_id": "my_postgres",
  "kind": "postgres",
  "config": {
    "host": "db.example.com",
    "port": 5432,
    "database": "analytics",
    "user": "readonly",
    "password": "secret"
  }
}
```

`db_id` pattern: `^[a-z0-9][a-z0-9_\-]{0,63}$`.

**Response** `201 Created`:
```json
{"db_id": "my_postgres"}
```

**Security:** Postgres connections enforce `default_transaction_read_only=on` plus session-level `statement_timeout` and a write-blocking regex.

---

### PATCH `/connections/{db_id}`

Update an existing connection's config.

**Response** `200 OK` -- updated connection.

---

### DELETE `/connections/{db_id}`

Remove a connection.

**Response:** `204 No Content`

---

### POST `/connections/test`

Test a connection without saving it. Useful for validating credentials before creating a connection.

**Request body:**
```json
{
  "db_id": "my_postgres",
  "kind": "postgres",
  "config": {
    "host": "db.example.com",
    "port": 5432,
    "database": "analytics",
    "user": "readonly",
    "password": "secret"
  }
}
```

**Response** `200 OK`:
```json
{
  "ok": true,
  "tables": ["users", "orders", "products"]
}
```

---

## 6. SQL Endpoint

### POST `/sql/execute`

Execute a read-only SQL query directly against a database. Write operations are blocked via regex (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `REPLACE`, `MERGE`, `GRANT`, `REVOKE`, `ATTACH`, `DETACH`). Additionally, SQLite databases get `PRAGMA query_only = ON`.

Results are capped at `SQL_ROW_LIMIT` (default: 1000 rows).

Prefix: `/api/v1`

**Request body:**
```json
{
  "db_id": "my_db",
  "sql": "SELECT transaction_type, COUNT(*) AS cnt FROM transactions GROUP BY transaction_type"
}
```

**Response** `200 OK`:
```json
{
  "columns": ["transaction_type", "cnt"],
  "rows": [
    {"transaction_type": "P2P", "cnt": 125000},
    {"transaction_type": "P2M", "cnt": 125000}
  ],
  "row_count": 2,
  "execution_time_ms": 12.34
}
```

**Errors:**
- `400 Bad Request` -- empty SQL, forbidden SQL keyword, or general SQL error
- `408 Request Timeout` -- query exceeded `SQL_TIMEOUT_SECONDS`

```bash
curl -X POST http://localhost:8080/api/v1/sql/execute \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"db_id":"my_db","sql":"SELECT COUNT(*) FROM transactions"}'
```

---

## 7. Insights Endpoints

Prefix: `/api/v1/insights`

Insights are AI-generated findings synthesized from chat responses, or manually created from assistant messages.

### GET `/insights`

List the current user's insights.

**Query parameters:**
- `bookmarked` -- If `true`, return only bookmarked insights (default: `false`)
- `limit` -- Number of insights (1--200, default: 50)

**Response** `200 OK`:
```json
{
  "insights": [
    {
      "id": "insight-abc",
      "title": "Revenue concentration in top 5 merchants",
      "summary": "The top 5 merchants account for 42% of all transaction volume...",
      "content": "Full markdown content...",
      "categories": ["revenue", "concentration"],
      "bookmarked": true,
      "user_note": "Important pattern to watch",
      "created_at": "2026-05-20T10:30:00"
    }
  ],
  "total": 12
}
```

---

### GET `/insights/all`

Admin-only cross-user insights feed.

**Response** `200 OK`:
```json
{
  "insights": [...]
}
```

---

### GET `/insights/count`

Return the current user's total insight count (for badge display).

**Response** `200 OK`:
```json
{"count": 12}
```

---

### POST `/insights`

Create a manual insight from an assistant message.

**Request body:**
```json
{
  "message_id": "msg002",
  "user_note": "Important pattern to watch"
}
```

**Response** `200 OK`:
```json
{"status": "ok", "id": "insight-abc"}
```

**Errors:**
- `404 Not Found` -- message not found
- `403 Forbidden` -- message belongs to another user

---

### PATCH `/insights/{insight_id}/bookmark`

Toggle bookmark on an insight.

**Request body:**
```json
{"bookmarked": true}
```

**Response** `200 OK`:
```json
{"status": "ok"}
```

**Errors:**
- `404 Not Found`

---

### DELETE `/insights/{insight_id}`

Delete an insight.

**Response** `200 OK`:
```json
{"status": "ok"}
```

**Errors:**
- `404 Not Found`

---

## 8. Feedback Endpoint

### POST `/api/v1/feedback`

Submit or update thumbs-up / thumbs-down feedback on an assistant message. Best-effort: updates the most recent `query_metrics` row for the conversation, never returns 500.

**Request body:**
```json
{
  "conversation_id": "abc123",
  "message_id": "msg002",
  "feedback": true,
  "comment": "Great answer, very accurate."
}
```

| Field | Type | Description |
|---|---|---|
| `conversation_id` | `string` | The conversation ID |
| `message_id` | `string` | The assistant message ID |
| `feedback` | `true` \| `false` \| `null` | `true` = thumbs up, `false` = thumbs down, `null` = clear feedback |
| `comment` | `string` \| `null` | Optional free-text comment |

**Response** `200 OK`:
```json
{"status": "ok"}
```

---

## 9. Shared Snapshots

Prefix: `/api/v1/conversations/{conversation_id}/share`

Create capability-token snapshots of a conversation that can be shared via a public URL. Viewer access is tracked but does not require authentication.

### POST `/share`

Create a share token for a conversation.

**Request body:**
```json
{
  "acknowledge_uploaded": false
}
```

**Response** `200 OK`:
```json
{
  "token": "abc123def456",
  "share_url": "/share/abc123def456",
  "created_at": 1716200000000,
  "expires_at": 1718800000,
  "revoked": false,
  "view_count": 0
}
```

**Gating rules:**
- Owner check: only the conversation owner can create a share
- Sharing-disabled flag: users with `sharing_disabled=true` get 403
- Uploaded-DB consent: sharing an uploaded SQLite chat requires `acknowledge_uploaded=true` (409 otherwise)
- Postgres/libsql refusal: sharing chats bound to live Postgres/libsql connections is refused (403)

**Errors:**
- `404 Not Found` -- conversation not found or not owned by caller
- `403 Forbidden` -- sharing disabled or Postgres/libsql refusal
- `409 Conflict` -- uploaded DB requires consent

---

### GET `/share`

Retrieve the share metadata for a conversation. Returns 404 if the conversation has never been shared.

**Response** `200 OK` -- same shape as POST response.

---

### DELETE `/share`

Soft-revoke a share token. The token remains in the database but will not resolve on the public viewer.

**Response:** `204 No Content`

---

## 10. Public Shares

Prefix: `/api/v1/public`

No authentication required.

### GET `/shares/{token}`

View a shared conversation snapshot. Increments the view count. Sets `Cache-Control: private, max-age=0, no-store` and `X-Robots-Tag: noindex, nofollow`.

**Response** `200 OK`:
```json
{
  "title": "Top merchant categories by volume",
  "dataset_name": "transactions_db",
  "messages": [
    {
      "role": "user",
      "content": "What are the top 5 merchant categories?",
      "created_at": 1716200000000
    },
    {
      "role": "assistant",
      "content": "The top 5 merchant categories are...",
      "created_at": 1716200005000
    }
  ],
  "created_at": 1716200000000,
  "expires_at": 1718800000
}
```

**Visibility checks:** token exists, not revoked, not expired. Returns 404 otherwise.

---

## 11. Automation Endpoints

Prefix: `/api/v1/automations`

All automation endpoints are gated behind `AUTOMATIONS_ENABLED=true`.

### GET `/automations`

List automations for the current user. Paginated.

**Query parameters:**
- `limit` -- Number of items (default: 50)
- `offset` -- Pagination offset (default: 0)

**Response** `200 OK` -- paginated array of automation objects.

---

### POST `/automations`

Create a new automation.

**Request body:**
```json
{
  "name": "Daily Fraud Alert",
  "db_id": "my_db",
  "trigger_condition": {
    "type": "threshold",
    "column": "fraud_count",
    "operator": "gt",
    "value": 100
  },
  "sql_queries": [
    "SELECT COUNT(*) AS fraud_count FROM transactions WHERE is_fraud = 1 AND date(timestamp) = date('now')"
  ],
  "schedule": {
    "preset": "daily"
  }
}
```

**Key constraints:**
- SQL validation: only SELECT statements, no multi-statement queries
- `db_id` validated against known databases -- returns 400 on unknown
- Per-user cap enforced atomically via `pg_advisory_xact_lock` (Postgres) / write-lock (SQLite) -- returns 429 when exceeded
- `AUTOMATIONS_MAX_PER_USER` (default 50)

**Response** `200 OK` -- created automation object.

---

### GET `/automations/{id}`

Get automation detail.

**Response** `200 OK` -- automation object with all fields.

---

### PUT `/automations/{id}`

Update an automation. All fields optional.

**Request body:**
```json
{
  "name": "Updated name",
  "schedule": {"preset": "weekly"},
  "sql_queries": ["SELECT COUNT(*) FROM transactions WHERE is_fraud = 1"],
  "trigger_condition": {...},
  "active": true
}
```

---

### DELETE `/automations/{id}`

Delete an automation.

**Response** `200 OK`:
```json
{"status": "ok"}
```

---

### POST `/automations/{id}/toggle`

Toggle an automation on/off.

**Response** `200 OK` -- updated automation object.

---

### POST `/automations/{id}/runs`

Manually trigger a run.

**Response** `200 OK`:
```json
{
  "status": "ok",
  "ran": [
    {
      "id": "run-xyz",
      "status": "success",
      "result_json": {"fraud_count": 45},
      "execution_time_ms": 234
    }
  ]
}
```

---

### GET `/automations/{id}/runs`

List run history for an automation.

**Query parameters:**
- `limit` -- Number of runs to return

**Response** `200 OK` -- array of run objects.

---

### GET `/automations/{id}/runs/{run_id}`

Get a specific run's detail.

**Response** `200 OK` -- single run object.

---

### POST `/automations/compile-trigger`

Compile a natural-language trigger description into structured JSON.

**Request body:**
```json
{
  "nl_text": "Alert when total fraud transactions exceed 1000",
  "available_columns": ["transaction_type", "amount", "is_fraud"]
}
```

**Response** `200 OK` -- compiled trigger condition JSON.

---

### POST `/automations/generate-sql`

Generate SQL from a natural-language prompt.

**Request body:**
```json
{"prompt": "Find transactions where the average amount per merchant exceeds 5000"}
```

**Response** `200 OK`:
```json
{"sql": "SELECT merchant_id, AVG(amount) ..."}
```

---

### Automation Templates (sub-router: `/api/v1/automations/templates`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | List templates (paginated) |
| POST | `/` | Create template |
| GET | `/{id}` | Get template detail |
| PUT | `/{id}` | Update template |
| DELETE | `/{id}` | Delete template |

---

## 12. Notification Endpoints

Prefix: `/api/v1/notifications`

Gated behind `AUTOMATIONS_ENABLED=true`.

### GET `/notifications`

List the current user's notifications.

**Query parameters:**
- `unread` -- If `true`, return only unread (default: `false`)
- `limit` -- Number of notifications (1--200, default: 50)

**Response** `200 OK` -- array of notification objects:
```json
[
  {
    "id": "notif-abc",
    "title": "Alert: Daily Fraud Alert triggered",
    "message": "fraud_count (145) exceeded threshold (100)",
    "severity": "warning",
    "is_read": false,
    "automation_name": "Daily Fraud Alert",
    "created_at": "2026-05-20T09:00:02"
  }
]
```

---

### GET `/notifications/all`

Admin-only cross-user notifications feed.

**Response** `200 OK` -- array of all users' notifications.

---

### GET `/notifications/count`

Return the current user's unread notification count.

**Response** `200 OK`:
```json
{"count": 3}
```

---

### GET `/notifications/stream`

SSE stream of live notifications. Hydrates the unread backlog on connect, then pushes new notifications as they arrive via a 15-second ping interval.

**Response:** `text/event-stream`

---

### POST `/notifications/{notification_id}/read`

Mark a single notification as read.

**Response** `200 OK`:
```json
{"status": "ok"}
```

**Errors:**
- `404 Not Found`

---

### POST `/notifications/mark-all-read`

Mark all of the current user's notifications as read.

**Response** `200 OK`:
```json
{"status": "ok", "count": 3}
```

---

## 13. Config Endpoints

### GET `/api/v1/config`

Get the current LLM provider and model configuration, plus available providers and their models.

**Response** `200 OK`:
```json
{
  "current_provider": "deepseek",
  "current_model": "deepseek-v4-flash",
  "providers": [
    {
      "provider": "gemini",
      "models": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash"
      ]
    },
    {
      "provider": "deepseek",
      "models": [
        "deepseek-v4-flash"
      ]
    }
  ]
}
```

---

### POST `/api/v1/config/switch`

Switch the active LLM provider and model at runtime. The change takes effect immediately for subsequent requests. Note: this is an in-process switch that is lost on restart.

**Request body:**
```json
{
  "provider": "gemini",
  "model": "gemini-2.5-pro"
}
```

**Response** `200 OK` -- updated config (same shape as GET).

---

### GET `/api/v1/client-config` (no auth)

Static feature-flag map for the frontend. No authentication required.

**Response** `200 OK`:
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

Feature flags reflect the server's configuration (e.g., `automations` and `notifications` are `false` when `AUTOMATIONS_ENABLED=false`).

---

## 14. Voice Endpoint

### WebSocket `/api/transcribe`

Real-time speech-to-text via Deepgram Nova-3. The browser sends binary audio frames (WebM/Opus); the server proxies them to Deepgram and relays transcription results back.

**Auth:** Session cookie (`ix_session`) sent with the WebSocket handshake, or `?token=` query parameter fallback.

**Close codes:**
| Code | Reason |
|---|---|
| `4001` | Not authenticated -- no valid session |
| `4002` | Speech-to-text not configured -- `DEEPGRAM_API_KEY` is empty |
| `1011` | Deepgram upstream connection failed |

**Transcription result (text message from server):**
```json
{
  "type": "Results",
  "channel": {
    "alternatives": [
      {
        "transcript": "What are the top merchant categories?",
        "confidence": 0.98
      }
    ]
  },
  "is_final": true
}
```

**Deepgram parameters** (sent by the server):
- `model`: `nova-3`
- `language`: `en`
- `punctuate`: `true`
- `interim_results`: `true`
- `utterance_end_ms`: `1000`
- `smart_format`: `true`

---

## 15. Health Endpoint

### GET `/api/v1/health`

Liveness/readiness probe. No authentication required.

**Response** `200 OK`:
```json
{"status": "ok"}
```

```bash
curl http://localhost:8080/api/v1/health
```

---

## 16. Prometheus Metrics

### GET `/metrics`

Prometheus text-format metrics. No authentication required (flagged `TODO-SECURITY`).

Exposed counters include:
- `audit_queue_depth` / `audit_overflow_total`
- `sse_active_emitters` / `sse_evicted_total`
- `llm_calls_total{source=...}`
- `process_resident_memory_bytes` / `process_open_fds`

```bash
curl http://localhost:8080/metrics
```

---

## 17. Admin Endpoints

All admin endpoints require `role == "admin"` on the authenticated user. Returns 403 otherwise.

### Overview (`/api/v1/admin/overview`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Aggregate KPIs: `active_users_24h`, `total_users`, `chats_today`, `tokens_today`, `thumbs_ratio_7d`, `sparkline_7d[]`. Cached 30s in-process. |

### Users (`/api/v1/admin/users`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | List all users (`id`, `email`, `role`, `is_active`, `must_change_password`, `last_seen_at`) |
| POST | `/` | Create user with `{email, role}`. Returns `{id, email, role, temp_password}`. 409 on duplicate email. |
| PATCH | `/{user_id}` | Update `{role?, is_active?}`. 409 if demoting the last admin. |
| POST | `/{user_id}/reset-password` | Generate a new temporary password. Returns `{temp_password}`. |
| DELETE | `/{user_id}` | Delete a user. 409 if deleting the last admin. |
| PATCH | `/{user_id}/sharing-disabled` | Toggle sharing capability: `{disabled: bool}`. |

### Databases (`/api/v1/admin/databases`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Admin-enriched DB list (owner email, share list) |
| PATCH | `/{db_id}` | Set `pipeline_mode_default` to `"linked"` or `"full_schema"` |

### RAG (`/api/v1/admin/rag`)

| Method | Path | Description |
|---|---|---|
| DELETE | `/qa-pairs` | Delete all QA pair embeddings. Returns `{deleted: true, count}`. |

### Prompts (`/api/v1/admin/prompts`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | List all prompts (DB-first resolution with file fallback) |
| GET | `/{name}` | Single prompt detail |
| PUT | `/{name}` | Upsert DB override: `{content, description?}`. Overrides the bundled `.j2` file. |
| DELETE | `/{name}` | Remove override, fall back to file. Returns `{deleted: true}`. |
| POST | `/{name}/reset` | Reset to file content. Returns `{reset: true}`. |

### Audit (`/api/v1/admin/audit`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Cursor-paginated audit log. Filters: `?user=&action=&from=&to=&cursor=&limit=`. Returns `{rows[], next_cursor?}`. |

### Metrics (`/api/v1/admin/metrics`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Cursor-paginated `query_metrics` rows. Filters: `?user=&db=&thumbs=&agent_mode=&from=&to=&cursor=&limit=`. |

### Conversations (`/api/v1/admin/conversations`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Cursor-paginated conversation list. Filters: `?user_id=&db_id=&cursor=&limit=`. |
| GET | `/{conv_id}` | Full detail with messages + parsed `chunks_json` |
| DELETE | `/{conv_id}` | Delete conversation. Returns `{deleted: true}`. |

### Performance (`/api/v1/admin/performance`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Per-endpoint latency percentiles (p50/p95/p99) from in-memory Prometheus histograms. Resets on restart. |

### Sentry Debug (`/api/v1/admin/sentry`)

| Method | Path | Description |
|---|---|---|
| GET | `/ping` | Emit a message-level Sentry event |
| GET | `/boom` | Raise `RuntimeError` to test exception capture |

---

## 18. Internal Endpoint

### POST `/api/internal/run-due-automations`

HMAC-authenticated endpoint for external scheduler (cron) integration. Only active when `AUTOMATIONS_ENABLED=true` and `AUTOMATIONS_SCHEDULER_MODE=external`.

**Auth:** `X-Scheduler-Signature` header with HMAC-SHA256 of the request body, keyed by `AUTOMATIONS_SCHEDULER_SECRET`.

**Request body:**
```json
{
  "tick_at": 1716200000
}
```

**Replay protection:** Max 5-minute drift on `tick_at`. 401 on bad signature.

**Response** `200 OK`:
```json
{
  "ran": [
    {"automation_id": "auto-abc", "run_id": "run-xyz", "status": "success"}
  ]
}
```

**Errors:**
- `401 Unauthorized` -- bad signature
- `503 Service Unavailable` -- automations disabled or scheduler mode is not `"external"`

```bash
BODY='{"tick_at":1716200000}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "your-secret-here" | awk '{print $2}')
curl -X POST http://localhost:8080/api/internal/run-due-automations \
  -H "Content-Type: application/json" \
  -H "X-Scheduler-Signature: $SIG" \
  -d "$BODY"
```

---

## 19. SSE Chunk Types Reference

All chunk types emitted by `POST /api/v1/chat` (and the legacy pipeline path). Every chunk follows the envelope: `{"type": "<ChunkType>", "data": {...}, "conversation_id": "...", "timestamp": 1234567890.0}`.

### Tier 1 -- Lifecycle Chunks

| Chunk Type | Description | Key Fields |
|---|---|---|
| `status` | Progress indicator | `data.message`, `data.stage` |
| `profile_loaded` | DB profile fetched from cache/store | `data.profile_summary` |
| `error` | An error occurred during processing | `data.message`, `data.stage` |
| `answer_delta` | Incremental text from the synthesizer LLM (streaming) | `data.delta` |
| `answer_generated` | Final synthesized answer (full markdown) | `data.answer`, `data.citations[]` |
| `metrics` | Token usage and timing for the completed response | `data.input_tokens`, `data.output_tokens`, `data.generation_time_ms` |
| `auto_routed` | Result of pre-flight mode classification | `data.mode`, `data.reason` |
| `few_shot_retrieved` | Few-shot examples retrieved from RAG | `data.count`, `data.examples[]` |

### Tier 2 -- Tool Call Chunks

| Chunk Type | Description | Key Fields |
|---|---|---|
| `tool_call` | LLM is invoking a tool | `data.tool_name`, `data.args`, `data.reasoning` |
| `tool_result` | Result of a tool execution | `data.tool`, `data.result`, `data.visualization`, `data.x_column`, `data.y_column` |

### Tier 3 -- Pipeline Transparency Chunks (Legacy 8-Stage Pipeline)

| Chunk Type | Stage | Description |
|---|---|---|
| `schema_linking_started` | SchemaLinker | Started linking schema for the question |
| `candidate_sqls_generated` | SchemaLinker | Candidate SQLs from few-shot examples |
| `literals_extracted` | SchemaLinker | Column literal values extracted |
| `semantic_matches` | SchemaLinker | Semantic column-to-question matches |
| `join_paths_added` | SchemaLinker | Join paths added to linked schema |
| `linked_schema_final` | SchemaLinker | Final linked schema (ready for SQL gen) |
| `sql_generated` | SqlGenerator | SQL query generated |
| `sql_executing` | SqlExecutor | SQL query execution started |
| `rows_returned` | SqlExecutor | Rows returned from execution |

### Tier 4 -- Orchestration Chunks (Agentic Mode)

| Chunk Type | Description | Key Fields |
|---|---|---|
| `orchestrator_plan` | Multi-agent task decomposition | `data.reasoning`, `data.tasks[{id, agent, task, depends_on, category}]` |
| `agent_trace` | Execution trace for a single orchestrator sub-task | `data.task_id`, `data.agent`, `data.final_sql`, `data.final_answer`, `data.success`, `data.steps[]` |
| `enrichment_trace` | Execution trace for an enrichment sub-task (legacy path) | `data.source_index`, `data.category`, `data.final_sql`, `data.final_answer`, `data.steps[]` |
| `insight` | Synthesized insight from multi-agent analysis | `data.content` (markdown with citations) |
| `clarification` | Clarifying question from the orchestrator | `data.question`, `data.skip_allowed` |

---

## Endpoint Summary

| Category | Endpoints | Auth |
|---|---|---|
| Auth | 4 (`login`, `logout`, `me`, `change-password`) | Mixed |
| Chat | 4 (`chat`, `poll`, `answer`, `route`) | Session |
| Conversations | 5 (`list`, `search`, `detail`, `update`, `delete`) | Session |
| Databases | 9 (`list`, `upload`, `upload-csv`, `schema`, `profile.get`, `profile.post`, `sample-questions`, `visibility`, `ensure-sample-questions`) | Mixed |
| Connections | 5 (`list`, `create`, `update`, `delete`, `test`) | Session |
| SQL | 1 (`execute`) | Session |
| Insights | 6 (`list`, `admin-list`, `count`, `create`, `bookmark`, `delete`) | Mixed |
| Feedback | 1 (`submit`) | Session |
| Shared Snapshots | 3 (`create`, `get`, `delete`) | Session |
| Public Shares | 1 (`view`) | None |
| Automations | 11+ (main 9 + templates 5 + templates CRUD) | Session |
| Notifications | 6 (`list`, `admin-list`, `count`, `stream`, `mark-read`, `mark-all-read`) | Mixed |
| Config | 3 (`config.get`, `switch`, `client-config`) | Mixed |
| Voice | 1 (WebSocket) | Cookie/Query |
| Health | 1 (`health`) | None |
| Metrics | 1 (`/metrics`) | None |
| Admin | ~18 across 9 sub-routers | Admin |
| Internal | 1 (`run-due-automations`) | HMAC |
| **Total** | **~68 endpoints** | |

---

_All SSE endpoints (chat, profiling, notification stream, orchestrator path) use `sse-starlette.EventSourceResponse` and terminate with `data: [DONE]`._
