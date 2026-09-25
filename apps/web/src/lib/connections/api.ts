// Typed connections API client (BYO external DB feature).
//
// Mirrors the pattern set by `lib/databases/api.ts`: every /api/v1/connections/*
// call lives here, and consumers (dialogs, hooks) never fetch those paths
// directly. Contract mirrors backend `routes/connections.py`.

import { apiFetch } from "@/lib/api";

export type ConnectionKind = "postgres" | "mysql" | "libsql" | "oracle";

export interface PostgresConfig {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl_mode: "disable" | "allow" | "prefer" | "require";
  schema: string;
}

export interface MySQLConfig {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl_enabled: boolean;
  charset: string;
}

export interface LibsqlConfig {
  url: string;
  auth_token: string;
}

export interface OracleConfig {
  host: string;
  port: number;
  service_name: string;
  /** Owner/schema to introspect. Empty = the login user's own schema. */
  schema: string;
  username: string;
  password: string;
  /** Raw alternative to host/port/service_name: a full `(DESCRIPTION=…)`
   *  TNS descriptor or an easy-connect `host[:port][/service]` string.
   *  Empty = use the fields above. */
  connection_string: string;
}

export type ConnectionConfig =
  | PostgresConfig
  | MySQLConfig
  | LibsqlConfig
  | OracleConfig;

export interface ConnectionRequest {
  db_id: string;
  kind: ConnectionKind;
  config: ConnectionConfig;
  /** Table-picker allowlist (oracle only). Omitted/empty = all tables. */
  selected_tables?: string[] | null;
}

export interface ConnectionTestResponse {
  ok: true;
  tables: string[];
  /** Oracle only: per-table row counts, column counts, unsupported columns. */
  details?: Record<
    string,
    {
      row_count: number | null;
      column_count: number;
      unsupported_columns: string[];
    }
  >;
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
): Promise<
  | { ok: true; tables: string[]; details?: ConnectionTestResponse["details"] }
  | { ok: false; error: string }
> {
  const res = await apiFetch("/api/v1/connections/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (res.ok) {
    const data = (await res.json()) as ConnectionTestResponse;
    return { ok: true, tables: data.tables, details: data.details };
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

