"use client";

// Admin Prompts hooks: list + get + put + delete + reset.
// Backends (Phase B3 Cluster 3.5):
//   GET    /api/v1/admin/prompts/            -> PromptSummary[]
//   GET    /api/v1/admin/prompts/{name}      -> PromptDetail
//   PUT    /api/v1/admin/prompts/{name}      -> { content, description? }
//   DELETE /api/v1/admin/prompts/{name}
//   POST   /api/v1/admin/prompts/{name}/reset

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export type PromptSource = "db" | "file";

export interface PromptSummary {
  name: string;
  has_override: boolean;
  is_active: boolean;
  description: string | null;
  updated_at: string | number | null;
  source: PromptSource;
}

export interface PromptDetail {
  name: string;
  content: string;
  file_content: string | null;
  source: PromptSource;
  description: string | null;
  is_active: boolean;
  updated_at: string | number | null;
}

const LIST_KEY = ["admin", "prompts"] as const;
const DETAIL_KEY = (name: string) => ["admin", "prompt", name] as const;

async function parseError(res: Response): Promise<Error> {
  let detail = "unknown";
  try {
    const body = (await res.json()) as { detail?: string };
    if (body?.detail) detail = body.detail;
  } catch {
    // ignore
  }
  return new Error(detail);
}

export function useAdminPrompts() {
  return useQuery({
    queryKey: LIST_KEY,
    queryFn: async () => {
      const res = await apiFetch("/api/v1/admin/prompts/");
      if (!res.ok) throw new Error(`prompts_list_failed_${res.status}`);
      return (await res.json()) as PromptSummary[];
    },
    staleTime: 120_000,
  });
}

export function useAdminPrompt(name: string | null) {
  return useQuery({
    queryKey: DETAIL_KEY(name ?? ""),
    enabled: !!name,
    queryFn: async () => {
      const res = await apiFetch(
        `/api/v1/admin/prompts/${encodeURIComponent(name!)}`,
      );
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as PromptDetail;
    },
    staleTime: 120_000,
  });
}

export interface SavePromptInput {
  name: string;
  content: string;
  description?: string | null;
}

export function useSavePrompt() {
  const qc = useQueryClient();
  return useMutation<PromptDetail, Error, SavePromptInput>({
    mutationFn: async ({ name, content, description }) => {
      const res = await apiFetch(
        `/api/v1/admin/prompts/${encodeURIComponent(name)}`,
        {
          method: "PUT",
          body: JSON.stringify({
            content,
            ...(description !== undefined ? { description } : {}),
          }),
        },
      );
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as PromptDetail;
    },
    onSuccess: (updated, vars) => {
      qc.setQueryData(DETAIL_KEY(vars.name), updated);
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}

export function useDeletePrompt() {
  const qc = useQueryClient();
  return useMutation<void, Error, { name: string }>({
    mutationFn: async ({ name }) => {
      const res = await apiFetch(
        `/api/v1/admin/prompts/${encodeURIComponent(name)}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw await parseError(res);
    },
    onSuccess: (_r, vars) => {
      void qc.invalidateQueries({ queryKey: DETAIL_KEY(vars.name) });
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}

export function useResetPrompt() {
  const qc = useQueryClient();
  return useMutation<PromptDetail | void, Error, { name: string }>({
    mutationFn: async ({ name }) => {
      const res = await apiFetch(
        `/api/v1/admin/prompts/${encodeURIComponent(name)}/reset`,
        { method: "POST" },
      );
      if (!res.ok) throw await parseError(res);
      try {
        return (await res.json()) as PromptDetail;
      } catch {
        return undefined;
      }
    },
    onSuccess: (_r, vars) => {
      void qc.invalidateQueries({ queryKey: DETAIL_KEY(vars.name) });
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}
