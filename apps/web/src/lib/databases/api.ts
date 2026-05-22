// Typed databases API client (Tier 1 profiling FE slice).
// Mirrors the pattern set by `lib/automations/api.ts`: every /api/v1/databases/*
// call lives here, and consumers (pages, hooks) never fetch those paths directly.
//
// Contract mirrors backend `routes/databases.py`. Any drift should ship
// with a matching backend change.

import { apiCall, apiFetch } from "@/lib/api";
import type {
  DatabaseListItem,
  DatabaseProfile,
  SchemaResponse,
} from "@/types/database";
import type { SampleQuestions } from "@/types/sample-questions";

/** Full profile response — extends DatabaseProfile with sample_questions. */
export interface ProfileResponse extends DatabaseProfile {
  sample_questions: SampleQuestions | null;
}

// List DBs visible to the caller.
//   GET /api/v1/databases → [{db_id, source}]
export function fetchDatabases(): Promise<DatabaseListItem[] | null> {
  return apiCall<DatabaseListItem[]>("/api/v1/databases");
}

// DDL + table names.
//   GET /api/v1/databases/{db_id}/schema
export function fetchSchema(dbId: string): Promise<SchemaResponse | null> {
  return apiCall<SchemaResponse>(
    `/api/v1/databases/${encodeURIComponent(dbId)}/schema`,
  );
}

// Cached profile. 404 → null (not profiled yet); other failures → null (logged).
//   GET /api/v1/databases/{db_id}/profile
export async function fetchProfile(
  dbId: string,
): Promise<ProfileResponse | null> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/profile`,
  );
  if (!res.ok) return null;
  try {
    return (await res.json()) as ProfileResponse;
  } catch {
    return null;
  }
}

// Update a single column profile field.
//   PATCH /api/v1/databases/{db_id}/profile/columns/{table}/{column}
export async function updateColumnProfile(
  dbId: string,
  tableName: string,
  columnName: string,
  fieldPath: string,
  value: unknown,
): Promise<boolean> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/profile/columns/${encodeURIComponent(tableName)}/${encodeURIComponent(columnName)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ field_path: fieldPath, value }),
    },
  );
  return res.ok;
}

// Revert a column profile field override to its generated value.
//   DELETE /api/v1/databases/{db_id}/profile/columns/{table}/{column}/overrides/{field_path}
export async function deleteColumnOverride(
  dbId: string,
  tableName: string,
  columnName: string,
  fieldPath: string,
): Promise<boolean> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/profile/columns/${encodeURIComponent(tableName)}/${encodeURIComponent(columnName)}/overrides/${encodeURIComponent(fieldPath)}`,
    { method: "DELETE" },
  );
  return res.ok;
}
