"use client";

// Cursor-paginated query_metrics infinite query. Filters are passed as params;
// the hook rebuilds when any filter changes. Pages flatten into a single rows
// list for the virtualized table.

import { useInfiniteQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export interface MetricsFilters {
  user?: string;
  db?: string;
  thumbs?: "up" | "down";
  agent_mode?: string;
  from?: number;
  to?: number;
  limit?: number;
}

// Shape from admin_metrics.py `_fetch`; fields mirror the query_metrics table.
// Kept loose because the backend serialises via `dict(r._mapping)` — any
// columns we don't explicitly type are still accessible.
export interface MetricsRow {
  id: string;
  created_at: number;
  user_id: string | null;
  user_email?: string | null;
  db_id: string | null;
  agent_mode: string | null;
  thumbs: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  sql?: string | null;
  question?: string | null;
  agent_trace_summary?: string | null;
  [extra: string]: unknown;
}

interface Page {
  rows: MetricsRow[];
  next_cursor: string | null;
}

function buildUrl(filters: MetricsFilters, cursor: string | null): string {
  const params = new URLSearchParams();
  if (filters.user) params.set("user", filters.user);
  if (filters.db) params.set("db", filters.db);
  if (filters.thumbs) params.set("thumbs", filters.thumbs);
  if (filters.agent_mode) params.set("agent_mode", filters.agent_mode);
  if (filters.from !== undefined) params.set("from", String(filters.from));
  if (filters.to !== undefined) params.set("to", String(filters.to));
  if (filters.limit) params.set("limit", String(filters.limit));
  if (cursor) params.set("cursor", cursor);
  const qs = params.toString();
  return `/api/v1/admin/metrics/${qs ? `?${qs}` : ""}`;
}

export function useAdminMetrics(filters: MetricsFilters) {
  return useInfiniteQuery({
    queryKey: ["admin", "metrics", filters],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const res = await apiFetch(buildUrl(filters, pageParam));
      if (!res.ok) throw new Error(`metrics_failed_${res.status}`);
      return (await res.json()) as Page;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 15_000,
  });
}
