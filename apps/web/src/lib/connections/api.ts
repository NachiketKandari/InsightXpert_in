// Typed connections API client (BYO external DB feature).
//
// Mirrors the pattern set by `lib/databases/api.ts`: every /api/v1/connections/*
// call lives here, and consumers (dialogs, hooks) never fetch those paths
// directly. Contract mirrors backend `routes/connections.py`.

import { apiFetch } from "@/lib/api";

export type ConnectionKind = "postgres" | "libsql";

export interface PostgresConfig {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl_mode: "disable" | "allow" | "prefer" | "require";
  schema: string;
}

export interface LibsqlConfig {
  url: string;
  auth_token: string;
}

export type ConnectionConfig = PostgresConfig | LibsqlConfig;

export interface ConnectionRequest {
  db_id: string;
  kind: ConnectionKind;
  config: ConnectionConfig;
}

export interface ConnectionTestResponse {
  ok: true;
  tables: string[];
}

export interface ConnectionListItem {
  db_id: string;
  kind: ConnectionKind;
  created_at: number;
}

/**
 * Validate a connection without saving — runs `SELECT 1` (or list_tables for
 * Postgres) against the target. Returns either the discovered table names or
 * a 400 with a `detail` message describing the failure.
 */
export async function testConnection(
  body: ConnectionRequest,
): Promise<{ ok: true; tables: string[] } | { ok: false; error: string }> {
  const res = await apiFetch("/api/v1/connections/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const data = (await res.json()) as ConnectionTestResponse;
    return { ok: true, tables: data.tables };
  }
  let detail = "Connection failed";
  try {
    const err = (await res.json()) as { detail?: string };
    if (err.detail) detail = err.detail;
  } catch {
    // body wasn't JSON; keep generic message
  }
  return { ok: false, error: detail };
}

/**
 * Persist a successfully-tested connection. Caller MUST call testConnection
 * first; the backend re-validates the config shape but doesn't open a
 * second connection here.
 */
export async function createConnection(
  body: ConnectionRequest,
): Promise<{ ok: true; db_id: string } | { ok: false; error: string }> {
  const res = await apiFetch("/api/v1/connections", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (res.status === 201 || res.ok) {
    const data = (await res.json()) as { db_id: string };
    return { ok: true, db_id: data.db_id };
  }
  let detail = "Save failed";
  try {
    const err = (await res.json()) as { detail?: string };
    if (err.detail) detail = err.detail;
  } catch {}
  return { ok: false, error: detail };
}

export async function listConnections(): Promise<ConnectionListItem[]> {
  const res = await apiFetch("/api/v1/connections");
  if (!res.ok) return [];
  return (await res.json()) as ConnectionListItem[];
}

export async function deleteConnection(dbId: string): Promise<boolean> {
  const res = await apiFetch(
    `/api/v1/connections/${encodeURIComponent(dbId)}`,
    { method: "DELETE" },
  );
  return res.ok || res.status === 204;
}
