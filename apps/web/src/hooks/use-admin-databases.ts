"use client";

// Admin databases hook. `GET /databases` returns the filtered list (admins
// see all). `POST /databases/{id}/visibility` is admin-only; we keep the
// mutation alongside the list query so the UI can update optimistically.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export type Visibility = "private" | "shared" | "public";

export interface AdminDatabase {
  db_id: string;
  source: string;
  // `GET /databases` currently returns only { db_id, source }. The visibility
  // table is authoritative on the server; a richer admin-dedicated endpoint
  // can fill in owner / shared_with later. For now the UI shows the source
  // and lets the admin set visibility directly.
}

const LIST_KEY = ["admin", "databases"] as const;

async function fetchDatabases(): Promise<AdminDatabase[]> {
  const res = await apiFetch("/api/v1/databases");
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
