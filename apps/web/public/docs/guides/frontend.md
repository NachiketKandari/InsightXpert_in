# Frontend Documentation

This guide covers the architecture, components, and patterns of the InsightXpert.ai frontend -- a Next.js 15+ application deployed on Vercel.

---

## Tech Stack

| Concern | Library / Version |
|---|---|
| Framework | Next.js 15+ (App Router, React Server Components) |
| UI runtime | React 19 |
| Language | TypeScript 5 (strict mode) |
| Styling | Tailwind CSS (utility-first) |
| Component primitives | shadcn/ui + Radix UI (accessible, unstyled primitives) |
| Client state | Zustand 5 |
| Animation | Framer Motion |
| Data visualization | Recharts |
| Streaming | Custom SSE client (`sse-client.ts`) |
| Markdown | react-markdown + remark-gfm |
| Syntax highlighting | react-syntax-highlighter |
| Toast notifications | Sonner |
| Monaco editor | @monaco-editor/react (SQL executor) |
| Fonts | Inter (body), JetBrains Mono (code), loaded via `next/font/google` |

---

## Project Structure

```
apps/web/src/
  app/                          # Next.js App Router pages
    layout.tsx                  # Root layout with providers, HealthCheckGate
    page.tsx                    # Main chat interface
    login/page.tsx              # Email + password login
    change-password/page.tsx    # Password change form
    automations/                # Automations list + new-automation dialog
    databases/                  # Database browser
      [id]/page.tsx             # Database detail page
    admin/                      # Admin dashboard
      overview/page.tsx         # Stats, active users, sparklines
      users/page.tsx            # User management
      databases/page.tsx        # Admin database controls
      automations/page.tsx      # Admin automations view
      prompts/page.tsx          # Prompt template admin
      rag/page.tsx              # pgvector store admin
      conversations/page.tsx    # Cross-user conversation viewer
      metrics/page.tsx          # Query metrics + cost tracking
      audit/page.tsx            # Audit log
      notifications/page.tsx    # Notification management
    share/[token]/page.tsx      # Public shared conversation viewer
  components/
    admin/                      # Admin UI components
    auth/                       # AuthGuard, login/register forms
    automations/                # Automation cards, dialogs, schedule/trigger builders
    chat/                       # Chat panel, messages, input, welcome screen
    chunks/                     # SSE chunk renderers (one per chunk type)
    databases/                  # Database cards, profile stepper, schema panel
    dataset/                    # CSV upload, dataset viewer
    health/                     # Health check gate
    insights/                   # Insight bell, popover, cards, modal
    layout/                     # App shell, header, sidebars, user menu
    notifications/              # Notification bell, popover, detail modal
    providers/                  # React context providers
    sample-questions/           # Sample questions modal
    share/                      # Share dialog
    sidebar/                    # Conversation list, process steps
    sql/                        # SQL executor, chart configurator
    ui/                         # shadcn/ui primitives (button, dialog, input, etc.)
  hooks/                        # Custom React hooks
    use-sse-chat.ts             # Main SSE chat hook
    use-voice-input.ts          # WebRTC voice recording + streaming
    use-databases.ts            # Database list with refetch
    use-theme.ts                # Dark/light mode toggle
    use-health-check.ts         # Backend availability polling
    use-auto-scroll.ts          # Chat auto-scroll
    use-media-query.ts          # Responsive breakpoint detection
    use-syntax-theme.ts         # Syntax highlighter theme resolution
    use-client-config.ts        # Feature flags + org branding
    use-sample-questions.ts     # Sample question generation + caching
    use-share.ts                # Chat sharing
    use-current-user.ts         # Auth state
    useProfileRun.ts            # Profile run SSE subscription
    use-admin-*.ts              # Admin data fetching hooks
    use-automation-runs.ts      # Automation run history
  lib/                          # Utility libraries
    api.ts                      # apiFetch, apiCall -- credentials + base URL
    sse-client.ts               # SSE streaming client
    chunk-parser.ts             # Chunk type routing and parsing
    chart-detector.ts           # Auto-detect chart type from SQL results
    footnote-parser.ts          # Citation footnote parsing
    citation-utils.ts           # Citation link extraction
    chunk-labels.ts             # Human-readable chunk type labels
    sql-utils.ts                # SQL formatting + validation
    constants.ts                # App-wide constants
    file-utils.ts               # File name/size formatting
    model-utils.ts              # Provider/model display helpers
    export-report.ts            # Export conversation as report
    utils.ts                    # General utilities
    automations/                # Automation API helpers
    databases/                  # Database API helpers
    connections/                # Connection API helpers
  stores/                       # Zustand stores
    chat-store.ts               # Conversations, streaming, active conversation
    settings-store.ts           # Provider, model, agent mode
    client-config-store.ts      # Feature flags, org branding
    insight-store.ts            # Insights with optimistic bookmark/delete
    notification-store.ts       # Notifications with optimistic mark-read
    automation-store.ts         # Automation CRUD, test triggers, templates
  types/                        # TypeScript type definitions
    chat.ts                     # ChatChunk, Message, Conversation, AgentStep
    chunks.ts                   # Typed chunk payloads
    database.ts                 # Database types, profile, join graph
    automation.ts               # Automation, TriggerCondition, Run types
    insight.ts                  # Insight types
    dataset.ts                  # Dataset types
    api.ts                      # API response shapes
    admin.ts                    # Admin-specific types
    sample-questions.ts         # Sample question types
```

---

## State Management

All client state uses Zustand stores. Here is the complete set:

### chat-store.ts

The central store. Persisted to `sessionStorage` (key `"insightxpert-chat"`). Message arrays are stripped on save and lazy-loaded from the server.

**Key state:**

| Field | Purpose |
|---|---|
| `conversations: Conversation[]` | All user conversations with messages in memory |
| `activeConversationId` | Currently selected conversation |
| `isStreaming`, `streamingConversationId` | Streaming state flags |
| `agentSteps: AgentStep[]` | Pipeline stage steps, populated in real time by `useSSEChat` |
| `selectedDbId` | Currently active database (persisted across reloads) |
| `leftSidebarOpen`, `rightSidebarOpen` | Sidebar visibility |
| `sqlExecutorOpen`, `datasetViewerOpen`, `sampleQuestionsOpen` | Modal/dialog visibility |
| `pendingClarification` | Set when a `clarification` chunk arrives |
| `skipClarificationNext` | Set when user clicks "Just answer" |
| `currentAgentPhase` | Current pipeline phase label (displayed in InputToolbar) |

**Key actions:** `initFromStorage`, `setActiveConversation`, `appendChunk`, `startAssistantMessage`, `finishStreaming`, `addAgentStep`, `updateAgentStep`.

### settings-store.ts

Not persisted. Manages LLM provider and model selection.

| Field | Purpose |
|---|---|
| `currentProvider`, `currentModel` | Active provider and model |
| `providers[]` | Available providers and their models (from `GET /api/v1/config`) |
| `agentMode` | `"basic"`, `"agentic"`, or `"auto"` |
| `pipelineMode` | `"auto"`, `"linked"`, or `"full_schema"` (admin-only override) |

`switchModel()` does an optimistic update and reverts on failure.

### client-config-store.ts

Fetched once on app load from `GET /api/v1/client-config`.

| Field | Purpose |
|---|---|
| `config.features` | Feature flag map: `{sql_runner, upload, profile_editor, voice, automations, admin, insights, notifications}` |
| `config.version` | Config version for cache busting |
| `isAdmin` | Whether the current user is an admin |
| `orgId` | Current user's organization ID |

On response, applies org branding CSS variables and forced color mode to `document.documentElement`.

### insight-store.ts

Session store for insights. Actions:

- `fetchInsights(bookmarked?)` -- fetch personal insights
- `fetchAllInsights()` -- admin: cross-user insights
- `fetchCount()` -- unread count for the bell badge
- `bookmarkInsight(id, bookmarked)` -- optimistic bookmark toggle with rollback
- `deleteInsight(id)` -- optimistic delete with rollback

### notification-store.ts

Session store for automation notifications. Actions:

- `fetchNotifications(unreadOnly?)` -- fetch user's notifications
- `fetchAllNotifications(unreadOnly?)` -- admin: cross-user notifications
- `fetchUnreadCount()` -- unread count for the bell badge
- `markAsRead(id)` -- optimistic mark-read with rollback
- `markAllAsRead()` -- optimistic mark-all-read with rollback

### automation-store.ts

Manages automation state. Actions:

- CRUD operations (create, fetch, update, delete, toggle)
- Manual run triggering with result tracking
- Test trigger state: client-side interval with live status
- Trigger template management
- New-automation dialog state

---

## SSE Client

The SSE client (`lib/sse-client.ts`) handles real-time streaming from the backend.

### Stream Lifecycle

1. `createSSEStream(message, conversationId, callbacks, agentMode, options, token?)` opens a `POST` to `/api/v1/chat`.
2. The response body is read as a `ReadableStream`, decoded line-by-line.
3. Each `data: <json>` SSE line is parsed into a chunk event.
4. `[DONE]` signals stream completion.
5. Chunks are enqueued and drained via `queueMicrotask` so all chunks from the same `reader.read()` batch are processed together, exploiting React 18 automatic batching.

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `message` | `string` | User's plain-English question |
| `conversationId` | `string \| null` | Conversation ID (null for new conversation) |
| `agentMode` | `"basic" \| "agentic" \| "auto"` | Pipeline mode selection |
| `options.dbId` | `string \| null` | Target database ID |
| `options.pipelineMode` | `"auto" \| "linked" \| "full_schema"` | Admin pipeline override |
| `options.skipClarification` | `boolean` | Skip clarification round |
| `token` | `string \| null` | Auth token for share pages |

Returns an `AbortController` for cancellation.

### Auto-Mode Routing

The default agent mode is `"auto"`. The server handles classification in the preflight phase (raced against profile prefetch, zero wall-clock cost) and emits an `auto_routed` chunk via SSE to inform the frontend of the routing decision. There is no client-side preflight call.

---

## useSSEChat Hook

`hooks/use-sse-chat.ts` is the main chat hook that wires SSE events into the Zustand store.

**Responsibilities:**

- Calls `createSSEStream` with the current agent mode, selected database, and pipeline mode.
- Dispatches each chunk type to `chat-store`:
  - `status`, `error`, `sql`, `answer`, `tool_call`, `tool_result`, `clarification`: appended as message chunks
  - `orchestrator_plan`, `agent_trace`: converted to `AgentStep` entries
  - `insight`: appended as chunks; triggers `insightStore.fetchCount()` on stream end
  - `metrics`: updates token counts and generation time on the message
  - `auto_routed`: updates the current agent phase label
- Tracks `lastRunningStepId` to mark the previous running step as `"done"` when the next phase begins.
- On `[DONE]`: records wall-clock time, calls `finishStreaming`.
- On stream error: appends an error chunk, calls `finishStreaming`.

---

## Chunk Renderers

The SSE pipeline emits typed chunks. `chunk-renderer.tsx` dispatches each to a typed component:

### Tier-1 (Always Present)

| Chunk type | Component | Description |
|---|---|---|
| `status` | `StatusChunk` | Progress bar with message label |
| `error` | `ErrorChunk` | Red error message with detail |
| `metrics` | (handled in store) | Token counts and generation time; never rendered directly |

### Tier-2 (Agentic Mode)

| Chunk type | Component | Description |
|---|---|---|
| `tool_call` | `ToolCallChunk` | Tool name and arguments display |
| `tool_result` | `ToolResultChunk` | Collapsible data table or raw JSON result |
| `clarification` | `ClarificationChunk` | Clarifying question with answer input |

### Tier-3 (Pipeline Transparency)

These chunks expose the internal pipeline stages for observability:

| Chunk type | Component | Description |
|---|---|---|
| `auto_routed` | `AutoRoutedChunk` | Auto-mode routing decision (basic vs agentic) |
| `few_shot_retrieved` | `FewShotRetrievedChunk` | Few-shot examples retrieved for SQL generation |
| `profile_loaded` | `ProfileLoadedChunk` | Schema profile loaded from cache |
| `schema_linking_started` | `SchemaLinkingStartedChunk` | Schema linking phase began |
| `candidate_sqls_generated` | `CandidateSqlsChunk` | Candidate SQL snippets found |
| `literals_extracted` | `LiteralsExtractedChunk` | LSH literal matching results |
| `semantic_matches` | `SemanticMatchesChunk` | Vector semantic search matches |
| `join_paths_added` | `JoinPathsAddedChunk` | FK join paths and bridge FKs discovered |
| `linked_schema_final` | `LinkedSchemaFinalChunk` | Final linked schema (subset of full schema) |
| `sql_generated` | `SqlGeneratedChunk` | Generated SQL with copy button |
| `sql_executing` | `SqlExecutingChunk` | SQL execution in progress |
| `rows_returned` | `RowsReturnedChunk` | Row count from SQL execution |
| `answer_delta` | (appended to answer) | Streaming answer tokens |
| `answer_generated` | `AnswerGeneratedChunk` | Final answer with execution time |

### Tier-4 (Orchestration)

| Chunk type | Component | Description |
|---|---|---|
| `orchestrator_plan` | Handled in store | Agentic execution plan |
| `agent_trace` | Handled in store | Per-agent step with duration and success |
| `insight` | `InsightChunk` | Cited markdown with `[^N]` footnote citations |
| `enrichment_trace` | Stored in chunks | Backing data for citation links |
| `stats_context` | `StatsContextChunk` | Pre-computed stats injected as context |
| `sql` | `SqlChunk` | Syntax-highlighted SQL with copy button (legacy) |
| `answer` | `AnswerChunk` | React.memo'd markdown with remark-gfm (legacy) |

### Profile SSE (Separate Stream)

| Chunk type | Component | Description |
|---|---|---|
| `profile_stage_started` | `ProfileStepper` | A profiling stage began |
| `profile_progress` | `ProfileStepper` | Batch progress within a stage |
| `profile_stage_completed` | `ProfileStepper` | Stage finished with duration |
| `profile_cost_estimate` | `CostConfirmModal` | Token cost estimate before profiling |
| `profile_done` | `ProfileStepper` | All stages complete |
| `profile_error` | `ProfileStepper` | Profile error |

### Supplementary Components

- **`ChartBlock`** (`components/chunks/chart-block.tsx`) -- auto-renders a Recharts chart from `tool_result` data. Lazy-loaded via `React.lazy`. Chart type determined by `detectChartType()`.
- **`DataTable`** (`components/chunks/data-table.tsx`) -- sortable, paginated table from SQL result rows.
- **`ThinkingTrace`** (`components/chunks/thinking-trace.tsx`) -- collapsible agentic mode trace showing orchestrator plan tasks and per-agent durations. Includes "View full trace" link.
- **`CitationLink`** (`components/chunks/citation-link.tsx`) -- inline `[^N]` badge that opens the `TraceModal` for the corresponding enrichment trace.
- **`TraceModal`** (`components/chunks/trace-modal.tsx`) -- full enrichment trace modal showing steps, SQL, and final answer for a citation.

---

## Chart Detection

`lib/chart-detector.ts` auto-detects chart types from SQL result columns and rows.

**Detection priority:**

1. **`grouped-bar`** -- exactly 2 category columns + 1 numeric column, more than 2 rows
2. **`pie`** -- 2-10 rows, exactly 1 category column + 1 numeric column
3. **`line`** -- any column matching `/date|month|year|day|week|quarter|time|period/i` with 3+ rows
4. **`bar`** -- 1+ category columns + 1+ numeric columns, more than 1 row
5. **`none`** -- fewer than 2 columns or no rows

Users can override the detected type via `ChartConfigurator` (pivots, axis selection).

---

## Chat Interface

### ChatPanel (`components/chat/chat-panel.tsx`)

Top-level chat orchestrator. Reads `activeConversation()` from `chat-store`. Renders one of:

1. A spinner while `isLoadingConversation` is true
2. `MessageList` + `MessageInput` when the conversation has messages
3. `WelcomeScreen` when starting a new conversation

### WelcomeScreen (`components/chat/welcome-screen.tsx`)

Shown when no messages exist. Displays categorized sample question prompts. Clicking a prompt sends it immediately.

### MessageInput (`components/chat/message-input.tsx`)

Auto-growing textarea. Enter submits; Shift+Enter inserts a newline. Shows a stop button during streaming.

### InputToolbar (`components/chat/input-toolbar.tsx`)

Sits below `MessageInput`. Contains:

- **Plus menu** (`+` button) -- dropdown with "Upload Database", "Connect Database", "SQL Executor", and pipeline mode selection
- **Agent mode selector** -- Basic / Agentic / Auto pill buttons, persisted in `settings-store`. During streaming, shows the current agent phase label
- **Model switcher** -- provider/model dropdown (shown when `model_switching` feature is enabled)
- **Voice input button** -- microphone toggle for real-time speech-to-text
- **Send / Stop button** -- send arrow when idle, stop square during streaming

### MessageBubble (`components/chat/message-bubble.tsx`)

Renders a single message. Assistant messages iterate over `message.chunks` and delegate each to `ChunkRenderer`. User messages render plain text. Includes `MessageActions` on hover (copy, feedback, retry).

### MessageList (`components/chat/message-list.tsx`)

Renders all messages. Auto-scrolls to bottom when `messages.length` changes or the last message's chunk count changes (avoids scroll-jacking on mid-stream updates).

### ShareDialog (`components/chat/share-dialog.tsx`)

Generates a capability-URL share link for the current conversation. Frozen at create time -- the share is a static snapshot. Accepts consent acknowledgement for uploaded databases.

---

## Layout Components

### AppShell (`components/layout/app-shell.tsx`)

Wraps the main chat page. Contains the header and two collapsible sidebars.

### Header (`components/layout/header.tsx`)

Contains:

- Left sidebar toggle button
- App logo
- Database selector (`DatasetSelector` dropdown)
- Model switcher (reads from `settings-store`)
- Documentation button (opens `DocsDialog`)
- Insight bell (`InsightBell`) with unread count badge
- Notification bell (`NotificationBell`) with unread count badge
- User menu (theme toggle, admin link if `is_admin`, change password, logout)

### Left Sidebar (`components/layout/left-sidebar.tsx`)

Fixed width on desktop; overlays on mobile. State in `chat-store.leftSidebarOpen`. Contains:

- "Chat History" heading with search icon
- Debounced search input (300ms, min 2 chars, calls `GET /api/v1/conversations/search?q=`)
- "New Chat" button
- `ConversationList` (scrollable) with rename/delete via context menu
- Pinned `UserMenu` at the bottom

### Right Sidebar (`components/layout/right-sidebar.tsx`)

Fixed width on desktop; overlays on mobile. State in `chat-store.rightSidebarOpen`. Shows "Agent Process" heading with `ProcessSteps` in a scroll area. Steps appear in real time during streaming.

### DatasetSelector (`components/layout/dataset-selector.tsx`)

Dropdown in the header to switch the active database. Lists all visible databases with source badges and profile indicators. Actions: select (activate), view (schema panel), upload, connect. Listens for `dataset-changed` custom events to stay in sync with uploads from other components.

### DocsDialog (`components/layout/docs-dialog.tsx`)

Full documentation browser accessible from the header book icon. Two-panel layout:

- Left sidebar: scrollable nav with grouped document links organized into "Overview" and "Guides" categories
- Right content area: fetches and renders the selected markdown file from `/docs/` with `ReactMarkdown` + `remark-gfm`

### UserMenu (`components/layout/user-menu.tsx`)

Avatar dropdown with user email, theme toggle, admin link (if admin), and logout.

---

## SQL Executor

`components/sql/sql-executor.tsx` provides direct SQL access to the selected database. Powered by Monaco editor with syntax highlighting. Submits to `POST /api/v1/sql/execute`. Write operations are blocked by the backend (read-only enforcement). Results render in `DataTable` with optional `ChartConfigurator`.

---

## Database Components

Located in `components/databases/`:

| Component | Purpose |
|---|---|
| `DatabaseCard` | Card showing database name, source, row/table counts, profile status |
| `ProfileStepper` | 7-stage progress display with live SSE updates |
| `ProfileStepRow` | Individual stage row (pending/running/done/error) |
| `CostConfirmModal` | LLM cost estimate before profiling begins |
| `StageCheckboxGroup` | Toggle which profiling stages to run |
| `SchemaPanel` | Browse tables, columns, join edges |
| `AutoDisableWarning` | Warning when column count exceeds max |

---

## Admin Dashboard

All admin pages are under `/admin` with a shared layout sidebar.

| Page | Purpose |
|---|---|
| **Overview** | Stats dashboard: active users (24h), total users, chats today, tokens today, 7-day thumbs ratio, 7-day sparkline |
| **Users** | User management: invite, role assignment (admin/user), activate/deactivate, reset password, delete |
| **Databases** | Admin database list with owner email, visibility controls, pipeline mode defaults |
| **Automations** | Cross-user automation view |
| **Prompts** | Prompt template admin: DB-first resolution, file fallback, override editor |
| **RAG** | pgvector store admin: clear QA pairs |
| **Conversations** | Cross-user conversation viewer with messages and chunks |
| **Metrics** | Query metrics and LLM cost tracking with filters |
| **Audit** | Audit log viewer with cursor pagination |
| **Notifications** | Cross-user notification management |

### Admin Components

| Component | Purpose |
|---|---|
| `FeatureToggles` | Toggle feature flags per org |
| `VirtualizedTable` | Virtualized data table for large datasets |
| `VisibilityMenu` | Database visibility controls (private/shared/public) |
| `ConversationViewer` | Full conversation replay with messages |

---

## Design System

### shadcn/ui

The UI is built on shadcn/ui components (`components/ui/`). These are Radix UI primitives styled with Tailwind CSS. Components are copied into the project (not a dependency) and can be customized.

### Tailwind CSS Theme

Theme tokens are defined in `tailwind.config.ts`. Dark and light mode are both supported, toggled via `useTheme()` hook which persists the preference to `localStorage` and falls back to the system preference (`prefers-color-scheme`).

### Org Branding

When `GET /api/v1/client-config` returns org branding data, CSS variables are applied to `document.documentElement` for per-organization theming. This includes logo, display name, color mode override, and CSS variable theme overrides.

### Fonts

- **Inter** for body text (loaded via `next/font/google`)
- **JetBrains Mono** for code (SQL, Monaco editor)
- Both fonts are applied as CSS variables for consistent theming

---

## Voice Input

`hooks/use-voice-input.ts` provides real-time speech-to-text via a WebSocket connection to the backend (`/api/transcribe`), which proxies audio to Deepgram Nova-3.

**State machine:** `"idle"` -> `"requesting"` (awaiting mic permission) -> `"listening"` (recording + transcribing).

**How it works:**

1. `start()` requests mic access, then opens a WebSocket to `{wsBaseUrl}/api/transcribe?token=...`.
2. A `MediaRecorder` (WebM/Opus, 250ms timeslice) sends audio binary frames over the WebSocket.
3. Incoming Deepgram JSON messages update committed and interim text buffers.
4. On `speech_final` from Deepgram, recording stops automatically.
5. A 10-second silence timer auto-stops if no speech is detected.
6. `prefixRef` accumulates text across multiple voice sessions for continuous dictation.
7. `clearVoiceText()` resets all buffers (called after sending a message).

**Error handling:** microphone denial, WebSocket failure, auth errors (WS close code 4001), unconfigured STT (WS close code 4002).

---

## Key Decisions

### npm workspaces over pnpm

The monorepo uses npm workspaces rather than pnpm due to Turbopack compatibility. All packages share a single lockfile at the root.

### shadcn/ui over custom components

shadcn/ui was chosen over building custom components because it provides accessible, unstyled Radix UI primitives with Tailwind styling that can be customized directly in the project. Components are copied into `components/ui/` and are owned by the project.

### sessionStorage for chat state

`chat-store` persists to `sessionStorage` (not `localStorage`). This means conversations survive page refreshes within a tab but not browser restarts. The trade-off prevents stale conversation data from persisting indefinitely while providing good UX during a session.

### Server-side auto-mode classification

The server classifies agent mode during preflight (raced against profile prefetch), avoiding a client-side `/chat/route` preflight call. This eliminates a round-trip and ensures the routing decision is made with access to the same context the pipeline uses.

### React.memo on expensive renderers

`AnswerChunk` and `InsightChunk` are wrapped with `React.memo` because they re-parse markdown on every render. Without memoization, every streaming chunk update would trigger a full markdown parse of the accumulated content, causing jank.

### Custom events for cross-component coordination

Database change events are coordinated across components via `window.dispatchEvent(new CustomEvent("dataset-changed", { detail }))`. This allows the `DatasetSelector` in the header to stay in sync with uploads triggered from `InputToolbar` or other components without prop drilling.

### Dual auth transport

Authentication supports both session cookies (`ix_session`, HttpOnly, SameSite=Lax) and `Authorization: Bearer <token>` headers. The cookie path is used by all page and API requests. The bearer path is used by WebSocket connections (voice input) and share pages.
