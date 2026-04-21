"use client";

// Admin databases hook. The enriched admin endpoint
// `GET /api/v1/admin/databases/` returns owner_email, canonical visibility,
// size_bytes, and the current `shared_with` list. Visibility changes still
// flow through `POST /api/v1/databases/{id}/visibility`.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export type Visibility = "private" | "shared" | "public";

export interface SharedWithEntry {
  user_id: string;
  email: string;
}

export interface AdminDatabase {
  db_id: string;
  owner_user_id: string | null;
  owner_email: string | null;
  visibility: Visibility;
  size_bytes: number | null;
  created_at: string | number | null;
  shared_with: SharedWithEntry[];
}

const LIST_KEY = ["admin", "databases"] as const;

async function fetchDatabases(): Promise<AdminDatabase[]> {
  const res = await apiFetch("/api/v1/admin/databases/");
  if (!res.ok) throw new Error(`list_failed_${res.status}`);
  return (await res.json()) as AdminDatabase[];
}

export function useAdminDatabases() {
  return useQuery({ queryKey: LIST_KEY, queryFn: fetchDatabases, staleTime: 30_000 });
}

export interface VisibilityInput {
  db_id: string;
  visibility: Visibility;
  shared_with?: string[];
}

export function useSetDbVisibility() {
  const qc = useQueryClient();
  return useMutation<void, Error, VisibilityInput>({
    mutationFn: async ({ db_id, visibility, shared_with }) => {
      const res = await apiFetch(
        `/api/v1/databases/${encodeURIComponent(db_id)}/visibility`,
        {
          method: "POST",
          body: JSON.stringify({ visibility, shared_with: shared_with ?? null }),
        },
      );
      if (!res.ok) {
        let detail = "failed";
        try {
          const body = (await res.json()) as { detail?: string };
          if (body?.detail) detail = body.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}
