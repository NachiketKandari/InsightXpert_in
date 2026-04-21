"use client";

// TanStack Query wrapper over /api/v1/admin/overview.
// Backend caches 30s in-process; we mirror that as the client-side staleTime.

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export interface OverviewSparklinePoint {
  day: number;
  chats: number;
  tokens: number;
}

export interface AdminOverview {
  active_users_24h: number;
  total_users: number;
  chats_today: number;
  tokens_today: number;
  thumbs_ratio_7d: number | null;
  sparkline_7d: OverviewSparklinePoint[];
}

async function fetchOverview(): Promise<AdminOverview> {
  const res = await apiFetch("/api/v1/admin/overview/");
  if (!res.ok) {
    throw new Error(`overview_failed_${res.status}`);
  }
  return (await res.json()) as AdminOverview;
}

export function useAdminOverview() {
  return useQuery({
    queryKey: ["admin", "overview"],
    queryFn: fetchOverview,
    staleTime: 30_000,
  });
}
