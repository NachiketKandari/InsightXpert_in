// ---------------------------------------------------------------------------
// Chunk-type → human label
// ---------------------------------------------------------------------------
// Lives in `lib/` (not co-located with trace-modal.tsx) so unit tests can
// import the label map without dragging the full TraceModal module — and
// its react-syntax-highlighter / react-markdown deps — into JSDOM.

/** Map of pipeline chunk-type strings to user-facing trace labels.
 *  Anything not in this map gets title-cased by `getChunkTypeLabel`. */
export const CHUNK_TYPE_LABELS: Record<string, string> = {
  profile_loaded: "Loaded database profile",
  schema_linking_started: "Linking schema",
  candidate_sqls_generated: "Drafted trial queries",
  literals_extracted: "Extracted literals",
  semantic_matches: "Matched columns semantically",
  join_paths_added: "Resolved join paths",
  linked_schema_final: "Linked schema ready",
  sql_generated: "Generated SQL",
  sql_executing: "Executing SQL",
  rows_returned: "Rows returned",
  answer_generated: "Generated answer",
  stats_context: "Retrieved dataset statistics",
  tool_call: "Tool call",
  tool_result: "Tool result",
  status: "Status",
  metrics: "Metrics",
};

/** Resolve a friendly label for a chunk-type string. Unknown snake_case types
 *  are title-cased (`foo_bar_baz` → `Foo Bar Baz`) rather than returned raw. */
export function getChunkTypeLabel(type: string): string {
  if (CHUNK_TYPE_LABELS[type]) return CHUNK_TYPE_LABELS[type];
  if (!type) return "";
  return type
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
