"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ProfileResponse } from "@/lib/databases/api";
import type { SampleQuestions } from "@/types/sample-questions";

export async function fetchProfile(dbId: string): Promise<ProfileResponse> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/profile`,
  );
  if (!res.ok) {
    throw new Error(`profile_fetch_failed_${res.status}`);
  }
  return (await res.json()) as ProfileResponse;
}

async function postRegenerate(dbId: string): Promise<void> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/sample-questions/regenerate`,
    { method: "POST" },
  );
  if (!res.ok && res.status !== 202) {
    throw new Error(`regenerate_failed_${res.status}`);
  }
}

async function postEnsure(dbId: string): Promise<{ status: string } | null> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/sample-questions/ensure`,
    { method: "POST" },
  );
  if (!res.ok) {
    // 404 (no profile yet) is expected — don't throw, just skip.
    if (res.status === 404) return null;
    throw new Error(`ensure_failed_${res.status}`);
  }
  return (await res.json()) as { status: string };
}

export function useSampleQuestions(dbId: string | undefined) {
  const qc = useQueryClient();

  const profileQuery = useQuery({
    queryKey: ["profile", dbId],
    enabled: Boolean(dbId),
    queryFn: () => fetchProfile(dbId!),
    staleTime: 30_000,
  });

  const regenerate = useMutation({
    mutationFn: () => postRegenerate(dbId!),
    onSuccess: () => {
      // Optimistically set status to "pending" in cache while SSE delivers the result
      qc.setQueryData(["profile", dbId], (prev: ProfileResponse | undefined) => {
        if (!prev) return prev;
        const pendingSq: SampleQuestions = prev.sample_questions
          ? { ...prev.sample_questions, status: "pending" }
          : {
              status: "pending",
              generated_at: null,
              model: null,
              categories: [],
              few_shot_db_ids: [],
              error: null,
            };
        return { ...prev, sample_questions: pendingSq };
      });
    },
  });

  const ensure = useMutation({
    mutationFn: () => postEnsure(dbId!),
    onSuccess: (result) => {
      if (result?.status === "pending") {
        // Optimistically set pending so the UI shows the skeleton on next
        // modal open, same as regenerate.
        qc.setQueryData(["profile", dbId], (prev: ProfileResponse | undefined) => {
          if (!prev) return prev;
          const pendingSq: SampleQuestions = prev.sample_questions
            ? { ...prev.sample_questions, status: "pending" }
            : {
                status: "pending",
                generated_at: null,
                model: null,
                categories: [],
                few_shot_db_ids: [],
                error: null,
              };
          return { ...prev, sample_questions: pendingSq };
        });
      }
    },
  });

  return {
    data: profileQuery.data?.sample_questions ?? undefined,
    profileQuery,
    regenerate,
    ensure,
  };
}
