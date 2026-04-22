export interface QueryResult {
  columns: string[];
  // Backend returns column-aligned arrays (list[list[Any]]) per
  // `SqlExecuteResponse` in routes/sql.py. Some older callers may still
  // receive `Record<string, unknown>[]` from legacy endpoints — consumers
  // should handle both defensively.
  rows: unknown[][] | Record<string, unknown>[];
  row_count: number;
  execution_time_ms: number;
}

export interface QueryError {
  /**
   * FastAPI's `detail` is either a plain string (domain errors) or an array
   * of validation-error objects (422s). Consumers MUST NOT render this
   * directly — use a coercion helper. See `sql-executor.tsx#coerceDetail`.
   */
  detail?: string | Array<{ msg?: string; type?: string; loc?: unknown; input?: unknown }>;
}
