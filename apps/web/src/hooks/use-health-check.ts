"use client";

// Polls the backend health endpoint via TanStack Query.
//
// Design notes:
// - Endpoint: /api/v1/health (FastAPI router is prefixed /api/v1). Goes through
//   Next's dev rewrite to the backend (see next.config.ts).
// - Defensive parsing: we only look at `res.ok`; any body shape is fine.
// - Backoff: when healthy, poll every 30s. When unhealthy, poll every 15s so
//   the banner clears quickly once the backend comes back. Probing on every
//   render or tighter intervals would flood the Next proxy with ECONNREFUSED
//   noise (Step 4 trade-off in the task brief).
// - Short fetch timeout (2s) so a hung backend doesn't pile up in-flight reqs.

import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "@/lib/constants";

const HEALTH_PATH = "/api/v1/health";
const FETCH_TIMEOUT_MS = 2_000;
const HEALTHY_POLL_MS = 30_000;
const UNHEALTHY_POLL_MS = 15_000;

async function probeHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}${HEALTH_PATH}`, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function useHealthCheck() {
  return useQuery({
    queryKey: ["backend-health"],
    queryFn: probeHealth,
    // Poll faster while unhealthy so we recover quickly; slower while green to
    // reduce the dev-server proxy-error flood.
    refetchInterval: (query) => (query.state.data === false ? UNHEALTHY_POLL_MS : HEALTHY_POLL_MS),
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 0,
  });
}
