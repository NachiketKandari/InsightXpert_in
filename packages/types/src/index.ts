/**
 * @insightxpert/types — hand-curated TS mirror of the backend Pydantic contracts.
 *
 * Source of truth: apps/api/src/insightxpert_api/sse/chunks.py and route Pydantic models.
 * Keep this file small; rebuild with codegen when the surface grows beyond eyeballing.
 */

// ============================================================================
// SSE chunk taxonomy
// ============================================================================

export type ChunkType =
  // inherited from public backend
  | "status"
  | "sql"
  | "tool_call"
  | "tool_result"
  | "answer"
  | "error"
  | "metrics"
  // v1 pipeline-internal transparency
  | "profile_loaded"
  | "schema_linking_started"
  | "candidate_sqls_generated"
  | "literals_extracted"
  | "semantic_matches"
  | "join_paths_added"
  | "linked_schema_final"
  | "sql_generated"
  | "sql_executing"
  | "rows_returned"
  | "answer_generated";

export interface StatusPayload {
  message: string;
}

export interface ErrorPayload {
  code: string;
  detail?: string | null;
}

export interface SQLPayload {
  sql: string;
}

export interface ToolCallPayload {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface ToolResultPayload {
  tool: string;
  result: unknown;
}

export interface AnswerPayload {
  text: string;
  final?: boolean;
}

export interface MetricsPayload {
  latency_ms: number;
  prompt_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  model?: string | null;
}

export interface ProfileLoadedPayload {
  db_id: string;
  table_count: number;
  column_count: number;
  from_cache: boolean;
}

export interface SchemaLinkingStartedPayload {
  question: string;
  db_id: string;
}

export interface CandidateSQLsGeneratedPayload {
  candidates: string[];
}

export interface LiteralsExtractedPayload {
  literals: string[];
  matches: Record<string, string[]>; // literal -> ["table.column", ...]
}

export interface SemanticMatch {
  column: string; // "table.column"
  score: number;
}

export interface SemanticMatchesPayload {
  matches: SemanticMatch[];
}

export interface JoinEdge {
  from: string; // "table.column"
  to: string; // "table.column"
  kind: "declared" | "value_verified" | "bridge" | string;
}

export interface JoinPathsAddedPayload {
  edges: JoinEdge[];
}

export interface LinkedSchemaFinalPayload {
  schema_text: string;
  linked_tables: string[];
  linked_columns: string[];
  column_sources: Record<string, string[]>;
  question_interpretation?: string | null;
}

export interface SQLGeneratedPayload {
  sql: string;
  iteration: number;
}

export interface SQLExecutingPayload {
  sql: string;
}

export interface RowsReturnedPayload {
  columns: string[];
  row_count: number;
  rows: Array<Array<unknown>>;
  execution_time_ms: number;
}

export interface AnswerGeneratedPayload {
  text: string;
}

/** Discriminated union over ``type`` for exhaustive renderer dispatch. */
export type ChatChunk =
  | { type: "status"; data: StatusPayload; conversation_id?: string | null; timestamp: number }
  | { type: "sql"; data: SQLPayload; conversation_id?: string | null; timestamp: number }
  | { type: "tool_call"; data: ToolCallPayload; conversation_id?: string | null; timestamp: number }
  | { type: "tool_result"; data: ToolResultPayload; conversation_id?: string | null; timestamp: number }
  | { type: "answer"; data: AnswerPayload; conversation_id?: string | null; timestamp: number }
  | { type: "error"; data: ErrorPayload; conversation_id?: string | null; timestamp: number }
  | { type: "metrics"; data: MetricsPayload; conversation_id?: string | null; timestamp: number }
  | { type: "profile_loaded"; data: ProfileLoadedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "schema_linking_started"; data: SchemaLinkingStartedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "candidate_sqls_generated"; data: CandidateSQLsGeneratedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "literals_extracted"; data: LiteralsExtractedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "semantic_matches"; data: SemanticMatchesPayload; conversation_id?: string | null; timestamp: number }
  | { type: "join_paths_added"; data: JoinPathsAddedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "linked_schema_final"; data: LinkedSchemaFinalPayload; conversation_id?: string | null; timestamp: number }
  | { type: "sql_generated"; data: SQLGeneratedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "sql_executing"; data: SQLExecutingPayload; conversation_id?: string | null; timestamp: number }
  | { type: "rows_returned"; data: RowsReturnedPayload; conversation_id?: string | null; timestamp: number }
  | { type: "answer_generated"; data: AnswerGeneratedPayload; conversation_id?: string | null; timestamp: number };

// ============================================================================
// Route request / response models
// ============================================================================

export interface ChatRequest {
  message: string;
  db_id: string;
  conversation_id?: string | null;
}

export interface ChatAnswerResponse {
  conversation_id: string;
  answer: string;
  sql: string[];
}

export interface ChatPollResponse {
  conversation_id: string;
  chunks: ChatChunk[];
}

export interface DatabaseRef {
  db_id: string;
  source: "bundled" | "uploaded";
}

export interface SchemaResponse {
  ddl: string;
  tables: string[];
}

export interface SqlExecuteRequest {
  db_id: string;
  sql: string;
}

export interface SqlExecuteResponse {
  columns: string[];
  rows: Array<Array<unknown>>;
  row_count: number;
  execution_time_ms: number;
}

export interface ConversationSummary {
  conversation_id: string;
  session_id: string;
  title?: string | null;
  starred: boolean;
  created_at: number;
  updated_at: number;
}

export interface ConversationDetail extends ConversationSummary {
  messages: Array<{ message_id: string; role: "user" | "assistant"; content: string; created_at: number }>;
  chunks: ChatChunk[];
}

export interface ClientConfig {
  features: {
    sql_runner: boolean;
    upload: boolean;
    profile_editor: boolean;
    voice: boolean;
    ollama: boolean;
    automations: boolean;
    admin: boolean;
    insights: boolean;
    notifications: boolean;
  };
  version: string;
}

export interface FeedbackRequest {
  conversation_id: string;
  message_id: string;
  feedback: boolean | null;
  comment?: string;
}

export interface UnlockRequest {
  password: string;
}

export interface MeResponse {
  session_id: string;
}

export interface ErrorResponse {
  error: string;
  detail?: string | null;
  status_code: number;
}
