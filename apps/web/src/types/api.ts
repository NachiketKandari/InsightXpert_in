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
