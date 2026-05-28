# InsightXpert.ai -- User Walkthrough

A practical guide to getting started and using every major feature.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Uploading or Connecting a Database](#2-uploading-or-connecting-a-database)
3. [Asking Your First Question](#3-asking-your-first-question)
4. [Understanding Results](#4-understanding-results)
5. [Profiling a Database](#5-profiling-a-database)
6. [Using Agentic Mode](#6-using-agentic-mode)
7. [Setting Up Automations](#7-setting-up-automations)
8. [Sharing Conversations](#8-sharing-conversations)
9. [Conversation Management](#9-conversation-management)
10. [Insights](#10-insights)
11. [Admin Features](#11-admin-features)

---

## 1. Getting Started

### Login

Open the app in your browser. You will see a login page with email and password fields. Enter your credentials to sign in.

If you are the first user, the admin account is auto-created on server startup from the `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` environment variables. If these are not set, you will need to register.

### Registration

If self-registration is enabled, click the register link on the login page. Fill in your email and password. After registration, you can log in immediately.

### Landing Page

After login, you will see the main chat interface:

- **Left sidebar**: Your conversation history, searchable, with create/rename/delete options.
- **Center**: The chat panel with a welcome screen showing sample questions.
- **Right sidebar**: (Visible during a query) Real-time agent process steps timeline.
- **Header**: Logo, model selector, SQL executor button, theme toggle, notification bell, insight bell, user menu.

---

## 2. Uploading or Connecting a Database

InsightXpert.ai supports three ways to bring your data:

### Option A: Bundled Sample Database

If the server ships with bundled databases in the configured `BUNDLED_DBS_DIR`, they appear automatically in the database selector. Select one to start querying immediately.

### Option B: Upload a SQLite File

1. Go to the databases section (accessible from the header or sidebar).
2. Click "Upload Database."
3. Drag and drop or browse for a `.sqlite`, `.db`, or `.sqlite3` file.
4. The system reads the schema, computes column statistics, and optionally generates LLM-powered column summaries and sample questions.

### Option C: Connect an External PostgreSQL Database

1. Go to Connections (accessible from the header).
2. Click "Add Connection" and fill in:
   - **Host** (e.g., `db.example.com`)
   - **Port** (default `5432`)
   - **Database name**
   - **Username** and **Password**
   - **SSL mode** (require, prefer, disable)
   - **Schema** (optional, defaults to `public`)
3. Credentials are encrypted at rest using Fernet symmetric encryption.
4. The connection is registered and appears in the database selector.

### Database Visibility

Databases have three visibility levels:
- **Private**: Only you can see and query it.
- **Shared**: Specific users you choose can access it.
- **Public**: All authenticated users can see and query it.

---

## 3. Asking Your First Question

### The Chat Interface

Type your question in plain English in the message input at the bottom of the chat panel. Press Enter or click the send button.

Example questions:
- "What is the total revenue by product category?"
- "Show me monthly active users for the last 6 months."
- "Which customers have the highest lifetime value?"
- "Compare sales performance between Q1 and Q2 this year."

### Pipeline Transparency

When you send a question, the 8-stage pipeline runs. You can watch each stage in real-time via the right sidebar's agent process timeline:

1. **Profiler**: Loads or generates the database profile (schema, column stats, summaries).
2. **Schema Linker**: Identifies the relevant tables, columns, and join paths for your question.
3. **SQL Generator**: Translates your question to SQL (shown as a syntax-highlighted code block).
4. **SQL Validator**: Checks the generated SQL for syntax errors.
5. **SQL Executor**: Runs the query against your database (results shown as a data table + chart).
6. **SQL Refiner**: If the query fails, retries with error context (up to 2 attempts).
7. **Answer Synthesizer**: Renders the results into a plain-English answer with streaming text.

Each stage emits SSE chunks that the frontend renders in real-time. You will see SQL appear, then a results table, then the answer text materializing word by word.

### Auto-Clarification

If your question is ambiguous, the system may ask a follow-up question rather than guessing. This is controlled by the `CLARIFICATION_ENABLED` setting and helps ensure accuracy.

### Thinking Trace

Click on any agent step in the right sidebar to expand a detailed thinking trace showing the SQL, results, LLM reasoning, and RAG context for that step.

---

## 4. Understanding Results

### Answer Structure

Every response includes:
- **Plain-English summary**: The direct answer to your question.
- **Supporting data**: Results table with the underlying query output.
- **Auto-detected chart**: Bar, line, pie, or grouped bar chart based on result shape.
- **SQL visibility**: The generated SQL query, viewable and copyable.

### Citations

In agentic mode, enriched insights include `[^1]`, `[^2]` footnote citations linking each claim to its supporting sub-agent analysis. Click a citation to see the source.

### Metrics

After each response completes, metrics are emitted showing:
- **Latency**: Total wall-clock time from send to `[DONE]`.
- **Token usage**: Input tokens, output tokens, and total.
- **Model**: Which LLM model generated the response.

### Follow-ups

You can ask follow-up questions in the same conversation. The system maintains conversation context (last 20 turns) so follow-ups build on prior answers.

---

## 5. Profiling a Database

### What Profiling Does

Profiling generates a structured `DatabaseProfile` for each database, containing:
- **Schema**: Tables, columns, types, primary keys, foreign keys.
- **Join graph**: Discovered FK relationships between tables.
- **Column statistics**: Row counts, null fractions, distinct counts, value ranges.
- **LLM summaries**: Batched per-column descriptions for natural language understanding.
- **LLM quirks**: Detected data quality issues (e.g., zero-meaning-null, enumeration constants).
- **Sample questions**: 9 starter questions (3 categories x 3 each) generated per database.

### When Profiling Runs

Profiling runs:
- **On upload**: When a new SQLite file is uploaded.
- **On first query**: If no cached profile exists, the ProfilerStage generates one on-demand.
- **On manual trigger**: You can re-profile a database from its settings.

### Cost Gating

Profiling uses LLM calls (for column summaries, quirk detection, and sample questions). To manage costs:
- **Batch processing**: Columns are sent to the LLM in batches (default 20 per call).
- **Auto-disable**: If a database has more than `PROFILING_MAX_COLUMNS_FOR_LLM` columns (default 500), LLM stages auto-disable and the profiler falls back to rule-based analysis.
- **Per-user daily cap**: `PROFILE_MAX_PER_USER_PER_DAY` (default 10) limits profiles per day.
- **Concurrency limit**: `PROFILE_MAX_CONCURRENCY` (default 2) caps parallel profiling LLM calls.

---

## 6. Using Agentic Mode

### What Agentic Mode Adds

In standard (linked) mode, you get a direct answer. In **agentic mode**, the system automatically enriches the answer with deeper analysis:

| Enrichment Category | What It Does |
|---|---|
| **Comparative Context** | Benchmarks your finding against a related group or time period |
| **Temporal Trend** | Checks if the pattern is growing, shrinking, or stable over time |
| **Root Cause** | Generates and tests hypotheses for why the pattern exists |
| **Segmentation** | Breaks the finding down by relevant dimensions (category, region, time, etc.) |

### How to Use It

1. In the input toolbar, switch the mode toggle from the current setting to **Agentic**.
2. Type your question and send.
3. You will see the analyst answer first (same as basic mode), then:
   - **Enrichment evaluation**: The system decides which enrichment categories are worthwhile.
   - **DAG execution**: Sub-agents run in parallel (sql_analyst for additional queries, quant_analyst for statistical tests).
   - **Synthesis**: All results are merged into a single cited insight with `[^1]`, `[^2]` footnote citations.
4. The final insight is quality-gated and, if it passes, persisted to the Insights panel.

### Auto Mode

Set the mode to **Auto** and the system will classify your question and choose the appropriate mode (basic for simple queries, agentic for complex ones). You can also see the classification reason in the response.

### Deep Think (Advanced)

For exhaustive exploration of a topic, Deep Think mode extracts 5W1H dimensions from your question and runs an investigation pipeline that evaluates completeness iteratively.

---

## 7. Setting Up Automations

Automations let you schedule recurring SQL queries with trigger-based alerting.

### Creating an Automation

1. Navigate to the Automations section.
2. Click "Create Automation."
3. **Describe in plain English**: Write what you want to monitor (e.g., "Check if daily revenue drops below $10,000"). The system generates the SQL.
4. **Or write SQL directly**: If you prefer, write the SQL queries manually.
5. **Set a schedule**: Choose a cron expression (e.g., "Every hour," "Daily at 9 AM," "Every Monday").
6. **Add triggers**: Define conditions that generate alerts:
   - **Threshold**: `revenue < 10000`
   - **Change detection**: % change from previous run
   - **Row count**: Whether results were returned
   - **Column expression**: Custom conditions on any column
7. **Save and enable**: The automation starts running on schedule.

### Workflow Builder (Multi-Step Automations)

For complex automations, you can build multi-step SQL workflows:

1. Add SQL blocks to the canvas (each block is a SQL query).
2. Connect blocks with edges to define dependencies.
3. The system auto-suggests edges based on shared table references.
4. SQL blocks execute in topological order.
5. Trigger conditions are evaluated against the final block's result.

### Monitoring Automations

- **Run history**: View every execution with status, results, and any triggers that fired.
- **Notifications**: When a trigger fires, you receive a notification (bell icon) with severity levels.
- **Toggle on/off**: Enable or disable automations without deleting them.

---

## 8. Sharing Conversations

### Creating a Share Link

1. Open the conversation you want to share.
2. Click the Share button.
3. The system creates a capability-token-based snapshot:
   - A 64-character random token is generated (`secrets.token_urlsafe(24)`).
   - The conversation's messages (with chunks) are frozen into a JSON payload at creation time.
   - The snapshot does not update if the original conversation changes.
4. Copy the share link and send it to anyone.

### Share Properties

- **Expiration**: Default 90 days, configurable.
- **View count**: Tracked per share.
- **Revocation**: You can revoke a share at any time.
- **Access control**: Shares are public URLs -- anyone with the link can view the snapshot.
- **Gating**: Sharing can be disabled per user (`sharing_disabled` flag). BYO Postgres databases may refuse sharing.

---

## 9. Conversation Management

### Sidebar

- **List**: All your conversations, ordered by most recent activity.
- **Search**: Full-text search across conversation titles and messages.
- **Star**: Pin important conversations to access them quickly.
- **Rename**: Click the conversation title to rename inline.
- **Delete**: Remove individual conversations.

### Lazy Loading

Conversation metadata loads on app start. Messages load on-demand when you click a conversation, keeping initial page load fast.

---

## 10. Insights

### How Insights Are Created

Insights are auto-generated during agentic/deep analysis. After the orchestrator's response synthesizer combines all sub-agent results, the quality gate evaluates the synthesized insight. If it passes, the insight is persisted.

### Accessing Insights

- **Bell icon** in the header shows a badge with unread count.
- **Popover**: Hover or click to see recent insights in a dropdown.
- **Gallery**: Click "View All" to open the full gallery with filtering and search.
- **Bookmark**: Save important insights for later reference.
- **Delete**: Remove insights you no longer need.

---

## 11. Admin Features

Admin users (determined by `role="admin"` or email domain matching `admin_domains` config) have access to additional features at `/admin`.

### Overview Dashboard

Shows high-level platform metrics: total users, databases, conversations, automations, and recent activity.

### User Management

- List all users with their roles, organizations, and activity status.
- Invite new users (creates account with temporary password, forces password change on first login).
- Change roles (admin/user).
- Deactivate or delete users.
- **Last Admin Guard**: The system prevents removing, demoting, or deactivating the last active admin.

### Prompt Management

- View all system prompt templates (both from vendored `.j2` files and from the database).
- Edit prompts live: changes take effect on the next chat turn without a server restart.
- Reset a prompt to its original vendored version.

### Feature Toggles (Client Config)

Control which features are available per organization:
- SQL executor visibility
- Model switching
- RAG training controls
- Chart rendering
- Conversation export
- Agent process sidebar
- Clarification enabled/disabled
- Stats context injection

### Organization Branding

Per-organization customization:
- Display name (shown in header and browser title)
- Logo URL
- CSS theme color overrides
- Color mode preference

### Database Management

- View all databases across the platform.
- Change visibility (private/shared/public).
- Manage shared users.

### RAG Management

- View vector store status per database.
- Clear RAG `qa_pairs` collection to reset few-shot examples.

### Conversation Viewer

Browse any user's conversations for support and debugging purposes.

---

*For technical architecture details, see [ARCHITECTURE.md](./ARCHITECTURE.md). For design patterns, see [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md).*
