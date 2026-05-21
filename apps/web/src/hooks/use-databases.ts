"use client";

// TanStack Query wrapper over /api/v1/databases.
// The list endpoint now includes has_profile + table/column/row counts, so
// DatabaseCard no longer needs a per-row fetch. 30s staleTime matches the
// global QueryClient default.

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { DatabaseListItem } from "@/types/database";

async function fetchDatabases(): Promise<DatabaseListItem[]> {
  const res = await apiFetch("/api/v1/databases");
  if (!res.ok) {
    throw new Error(`databases_list_failed_${res.status}`);
  }
  return (await res.json()) as DatabaseListItem[];
}

export function useDatabases() {
  return useQuery({
    queryKey: ["databases", "list"],
    queryFn: fetchDatabases,
    staleTime: 120_000,
  });
}
