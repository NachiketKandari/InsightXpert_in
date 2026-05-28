"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

const THRESHOLD_KEY = ["admin", "threshold"] as const;

interface ThresholdResponse {
  threshold: number;
}

async function fetchThreshold(): Promise<number> {
  const res = await apiFetch("/api/v1/config/threshold");
  if (!res.ok) throw new Error(`fetch_threshold_failed_${res.status}`);
  const data = (await res.json()) as ThresholdResponse;
  return data.threshold;
}

export function useAdminThreshold() {
  return useQuery({
    queryKey: THRESHOLD_KEY,
    queryFn: fetchThreshold,
    staleTime: 300_000,
  });
}

export function useUpdateAdminThreshold() {
  const qc = useQueryClient();
  return useMutation<number, Error, number>({
    mutationFn: async (threshold: number) => {
      const res = await apiFetch("/api/v1/config/threshold", {
        method: "POST",
        body: JSON.stringify({ threshold }),
      });
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
      const data = (await res.json()) as ThresholdResponse;
      return data.threshold;
    },
    onSuccess: (data) => {
      qc.setQueryData(THRESHOLD_KEY, data);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: THRESHOLD_KEY });
    },
  });
}
