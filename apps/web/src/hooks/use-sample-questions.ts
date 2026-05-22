"use client";

import { useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ProfileResponse } from "@/lib/databases/api";
import type { SampleQuestions } from "@/types/sample-questions";

function anySignal(...signals: (AbortSignal | undefined)[]): AbortSignal {
  const defined = signals.filter((s): s is AbortSignal => s != null);
  if (defined.length === 0) return new AbortController().signal;
  if (defined.length === 1) return defined[0];
  return AbortSignal.any(defined);
}

export async function fetchProfile(
  dbId: string,
  signal?: AbortSignal,
): Promise<ProfileResponse> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/profile`,
    { signal },
  );
  if (!res.ok) {
    throw new Error(`profile_fetch_failed_${res.status}`);
  }
  return (await res.json()) as ProfileResponse;
}

export async function postRegenerate(dbId: string): Promise<void> {
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

export interface SampleQuestionsStatus {
  status: "ok" | "fallback" | "pending" | "failed" | "not_found";
  generated_at: string | null;
  model: string | null;
  progress: { current: number; total: number } | null;
  error: string | null;
}

async function fetchSampleQuestionsStatus(
  dbId: string,
): Promise<SampleQuestionsStatus> {
  const res = await apiFetch(
    `/api/v1/databases/${encodeURIComponent(dbId)}/sample-questions/status`,
  );
  if (!res.ok) throw new Error(`status_fetch_failed_${res.status}`);
  return (await res.json()) as SampleQuestionsStatus;
}

export function useSampleQuestions(dbId: string | undefined) {
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  // Cancel in-flight profile fetch when dbId changes (rapid DB switching).
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [dbId]);

  const profileQuery = useQuery({
    queryKey: ["profile", dbId],
    enabled: Boolean(dbId),
    queryFn: ({ signal }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      return fetchProfile(dbId!, anySignal(signal, controller.signal));
    },
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

/** Polls GET /sample-questions/status every 2s while generation is in flight. */
export function useSampleQuestionStatus(dbId: string | undefined) {
  return useQuery({
    queryKey: ["sample-questions-status", dbId],
    enabled: Boolean(dbId),
    queryFn: () => fetchSampleQuestionsStatus(dbId!),
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? 2000 : false,
    staleTime: 0,
  });
}

/** Explicit "Generate" action that calls POST /ensure and invalidates both
 *  the profile cache and the status poller. */
export function useGenerateSampleQuestions(dbId: string | undefined) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: () => postEnsure(dbId!),
    onSuccess: (result) => {
      if (result?.status === "pending") {
        // Mark the profile cache as pending so the UI shows the progress bar.
        qc.setQueryData(
          ["profile", dbId],
          (prev: ProfileResponse | undefined) => {
            if (!prev) return prev;
            return {
              ...prev,
              sample_questions: {
                status: "pending",
                generated_at: null,
                model: null,
                categories: [],
                few_shot_db_ids: [],
                error: null,
              },
            };
          },
        );
      }
      // Invalidate both caches so the status poller picks up immediately.
      qc.invalidateQueries({ queryKey: ["sample-questions-status", dbId] });
      qc.invalidateQueries({ queryKey: ["profile", dbId] });
    },
  });
}
