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
): Promise<DatabaseProfile | null> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/profile`,
  );
  if (!res.ok) return null;
  try {
    return (await res.json()) as DatabaseProfile;
  } catch {
    return null;
  }
}
