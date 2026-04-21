"use client";

// Cursor-paginated audit-log infinite query. Mirrors use-admin-metrics.

import { useInfiniteQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export interface AuditFilters {
  user?: string;
  action?: string;
  from?: number;
  to?: number;
  limit?: number;
}

export interface AuditRow {
  id: string;
  created_at: number;
  user_id: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  ip: string | null;
  [extra: string]: unknown;
}

interface Page {
  rows: AuditRow[];
  next_cursor: string | null;
}

function buildUrl(filters: AuditFilters, cursor: string | null): string {
  const params = new URLSearchParams();
  if (filters.user) params.set("user", filters.user);
  if (filters.action) params.set("action", filters.action);
  if (filters.from !== undefined) params.set("from", String(filters.from));
  if (filters.to !== undefined) params.set("to", String(filters.to));
  if (filters.limit) params.set("limit", String(filters.limit));
  if (cursor) params.set("cursor", cursor);
  const qs = params.toString();
  return `/api/v1/admin/audit/${qs ? `?${qs}` : ""}`;
}

export function useAdminAudit(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: ["admin", "audit", filters],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const res = await apiFetch(buildUrl(filters, pageParam));
      if (!res.ok) throw new Error(`audit_failed_${res.status}`);
      return (await res.json()) as Page;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 15_000,
  });
}
