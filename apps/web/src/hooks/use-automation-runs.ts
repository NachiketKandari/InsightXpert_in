"use client";

// TanStack Query wrapper over GET /api/v1/automations/{id}/runs.
// Replaces the raw useEffect+fetch pattern that re-ran every time an
// AutomationCard was expanded. 30s staleTime matches the global default;
// runNow mutations invalidate via invalidateAutomationRuns().

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchRunHistory } from "@/lib/automations/api";
import type { AutomationRun } from "@/types/automation";

export const automationRunsKey = (id: string, limit = 20) =>
  ["automations", id, "runs", limit] as const;

async function queryFn(id: string, limit: number): Promise<AutomationRun[]> {
  const data = await fetchRunHistory(id, limit);
  if (data === null) {
    throw new Error(`automation_runs_failed_${id}`);
  }
  return data;
}

export function useAutomationRuns(id: string, limit = 20) {
  return useQuery({
    queryKey: automationRunsKey(id, limit),
    queryFn: () => queryFn(id, limit),
    staleTime: 30_000,
  });
}

/** Call after a successful runNow / delete-run / similar mutation. */
export function useInvalidateAutomationRuns() {
  const qc = useQueryClient();
  return (id: string) =>
    qc.invalidateQueries({ queryKey: ["automations", id, "runs"] });
}
