/**
 * Contract mirrors for the `databases` route family.
 *
 * Source of truth:
 *   - List/upload/schema shapes: apps/api/src/insightxpert_api/routes/databases.py
 *   - DatabaseProfile: apps/api/src/insightxpert_api/vendored/pipeline_core/models/profile.py
 *   - SSE chunk payloads: apps/api/src/insightxpert_api/sse/chunks.py
 *
 * Keep narrow — only fields the UI renders. Extend as needs grow.
 */

export type DatabaseSource = "bundled" | "uploaded" | "postgres" | "libsql";

export interface DatabaseListItem {
  /** Stable short identifier, e.g. `california_schools` or a user upload slug. */
  db_id: string;
  /** "bundled" | "uploaded" — lowercased origin tag. */
  source: string;
  /** True if a base profile row exists for this db. */
  has_profile: boolean;
  /** Populated when has_profile is true; null otherwise. */
  table_count: number | null;
  column_count: number | null;
  row_count: number | null;
  /** Owner user ID — null for bundled/seeded DBs with no owner row. */
  owner_user_id: string | null;
}

export interface DatabaseUploadResponse {
  db_id: string;
  source: string;
  profile_required?: boolean;
}

// --- Upload preview (read-only, before upload) ----------------------------

export interface PreviewColumn {
  name: string;
  inferred_type: string;
  sample_values: string[];
  null_count: number;
  distinct_count: number;
}

export interface SheetPreview {
  sheet_name: string;
  columns: PreviewColumn[];
  preview_rows: Record<string, string>[];
  row_count: number;
}

export interface UploadPreviewResponse {
  columns: PreviewColumn[];
  preview_rows: Record<string, string>[];
  row_count: number;
  encoding: string | null;
  sheet_name: string | null;
  sheet_names: string[] | null;
  sheets: SheetPreview[] | null;
  file_size_bytes: number;
}

export interface SchemaResponse {
  ddl: string;
  tables: string[];
}

// --- DatabaseProfile (cached profile payload) -----------------------------

export interface ColumnStats {
  count: number;
  null_count: number;
  distinct_count: number;
  min_value: string | null;
  max_value: string | null;
  sample_values: string[];
}

export interface ColumnQuirks {
  has_special_chars?: boolean;
  numbered_group?: string | null;
  fk_alias?: string | null;
  type_mismatch?: string | null;
  symbolic_values?: boolean;
  enum_labels?: Record<string, string>;
  semantic_hint?: string;
  aliases?: string[];
}

export interface ColumnProfile {
  name: string;
  type: string;
  stats: ColumnStats;
  mechanical_description: string;
  short_summary: string;
  long_summary: string;
  bird_enriched_summary: string;
  quirks: ColumnQuirks;
}

export interface TableProfile {
  name: string;
  row_count: number;
  columns: ColumnProfile[];
  description: string;
}

export interface DatabaseProfile {
  db_id: string;
  tables: TableProfile[];
}

// --- Profile run request + SSE payloads -----------------------------------

export interface ProfileFlags {
  with_summaries: boolean;
  with_quirks: boolean;
  with_lsh: boolean;
  with_vectors: boolean;
  with_table_descriptions: boolean;
}

export interface ProfileRunRequest extends ProfileFlags {
  confirmed: boolean;
  user_hints?: string;
}

export type ProfileStage =
  | "schema"
  | "stats"
  | "join_graph"
  | "summaries"
  | "quirks"
  | "lsh"
  | "vectors"
  | "table_descriptions";

export const PROFILE_STAGE_ORDER: readonly ProfileStage[] = [
  "schema",
  "stats",
  "join_graph",
  "summaries",
  "quirks",
  "lsh",
  "vectors",
  "table_descriptions",
] as const;

export interface ProfileStageStartedPayload {
  stage: ProfileStage;
  db_id: string;
}

export interface ProfileStageCompletedPayload {
  stage: ProfileStage;
  db_id: string;
  duration_ms: number;
  /** "skipped" when the flag was off or auto-disabled; null otherwise. */
  note: string | null;
}

export interface ProfileProgressPayload {
  stage: ProfileStage;
  batch_index: number;
  batch_total: number;
}

export interface ProfileCostEstimatePayload {
  columns: number;
  batch_size: number;
  total_llm_calls: number;
  estimated_seconds: number;
  provider?: string | null;
  model?: string | null;
}

export interface ProfileDonePayload {
  db_id: string;
  table_count: number;
  column_count: number;
  summaries_populated: number;
  total_duration_ms?: number;
}

export interface ProfileErrorPayload {
  db_id: string;
  message: string;
}

export type ProfileChunk =
  | { type: "profile_stage_started"; payload: ProfileStageStartedPayload }
  | { type: "profile_stage_completed"; payload: ProfileStageCompletedPayload }
  | { type: "profile_progress"; payload: ProfileProgressPayload }
  | { type: "profile_cost_estimate"; payload: ProfileCostEstimatePayload }
  | { type: "profile_done"; payload: ProfileDonePayload }
  | { type: "profile_error"; payload: ProfileErrorPayload };

/**
 * FE-side mirror of backend PROFILING_MAX_COLUMNS_FOR_LLM. Deploy-time
 * constant; surfaced in the auto-disable warning copy.
 */
export const PROFILING_MAX_COLUMNS_FOR_LLM = 500;

// --- Profile editing (interfaces removed during orphan cleanup D-090) ---------
