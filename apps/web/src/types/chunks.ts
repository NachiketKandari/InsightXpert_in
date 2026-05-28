/**
 * Tier-3 pipeline transparency chunk payload shapes.
 *
 * Source of truth: `apps/api/src/insightxpert_api/sse/chunks.py`. Keep these
 * in sync when backend payloads change. Every chunk uses the strict envelope
 * `{type, data, conversation_id, timestamp}` — these types describe the
 * `data` field contents per chunk type.
 */

export interface ProfileLoadedData {
  db_id: string;
  table_count: number;
  column_count: number;
  from_cache: boolean;
}

export interface SchemaLinkingStartedData {
  question: string;
  db_id: string;
}

export interface CandidateSQLsGeneratedData {
  candidates: string[];
}

export interface LiteralsExtractedData {
  literals: string[];
  /** Map of literal → list of column names it matched. */
  matches: Record<string, string[]>;
}

export interface SemanticMatch {
  column: string;
  score: number;
}

export interface SemanticMatchesData {
  matches: SemanticMatch[];
}

export interface JoinEdge {
  from: string;
  to: string;
  kind: string;
}

export interface JoinPathsAddedData {
  edges: JoinEdge[];
}

/** Source tags used in `column_sources`: one or more of these per column. */
export type ColumnSource = "trial_sql" | "semantic" | "lsh" | "join_path";

export interface LinkedSchemaFinalData {
  schema_text: string;
  linked_tables: string[];
  linked_columns: string[];
  /** column name → list of source tags that contributed it. */
  column_sources: Record<string, ColumnSource[] | string[]>;
  question_interpretation?: string | null;
}

export interface SqlGeneratedData {
  sql: string;
  iteration: number;
}

export interface SqlExecutingData {
  sql: string;
}

export interface RowsReturnedData {
  columns: string[];
  row_count: number;
  /**
   * On the wire rows come as `list[list]` (each row is an array of cells
   * aligned to `columns`). We also accept `list[dict]` for forward-compat
   * — the `RowsReturnedChunk` renderer normalizes both.
   */
  rows: unknown[][] | Array<Record<string, unknown>>;
  execution_time_ms: number;
}

export interface AnswerGeneratedData {
  text: string;
}

/**
 * Per-DB few-shot QA pair retrieved during the route's preflight.
 *
 * Emitted as a single ``few_shot_retrieved`` chunk before any pipeline
 * activity, so the trace UI can show "we pulled this similar example" up
 * front. The same pair is then threaded into the SQL-gen prompt's
 * ``{% if few_shot_example %}`` block.
 */
export interface FewShotRetrievedData {
  question: string;
  gold_sql: string;
  similarity: number;
  source_db_id: string;
}
