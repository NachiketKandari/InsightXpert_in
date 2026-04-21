"use client";

// Admin RAG hook: single mutation to clear all learned QA pairs.
//   DELETE /api/v1/admin/rag/qa-pairs -> { deleted: true, count: number | null }

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export interface ClearQaPairsResult {
  deleted: boolean;
  count: number | null;
}

export function useClearQaPairs() {
  return useMutation<ClearQaPairsResult, Error, void>({
    mutationFn: async () => {
      const res = await apiFetch("/api/v1/admin/rag/qa-pairs", {
        method: "DELETE",
      });
      if (!res.ok) {
        let detail = "unknown";
        try {
          const body = (await res.json()) as { detail?: string };
          if (body?.detail) detail = body.detail;
        } catch {
          // ignore
        }
        throw new Error(detail);
      }
      return (await res.json()) as ClearQaPairsResult;
    },
  });
}
