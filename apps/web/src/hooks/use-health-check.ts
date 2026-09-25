"use client";

// Polls the backend health endpoint via TanStack Query.
//
// Design notes:
// - Two probe targets; healthy if EITHER answers 2xx:
//     1. Same-origin `/api/v1/health` — the exact path the app's regular API
//        calls use (Vercel rewrite → api.insightxpert.in in production). If
//        this path works, the app works.
//     2. `${SSE_BASE_URL}/api/v1/health` — the direct-to-backend path SSE
//        streams use. Kept as a fallback: if the Vercel/Next proxy hiccups the
//        direct probe still succeeds, and if a client network can't reach the
//        api subdomain directly the same-origin probe still succeeds. Only
//        when BOTH fail is the backend genuinely unreachable from this tab.
// - Real retry: a failed cycle (both targets) is retried once after a short
//   delay, with the retry living HERE — React Query's `retry` never fires for
//   a queryFn that resolves, and probeHealth resolves `false` instead of
//   throwing. Without this, one transient blip painted the banner for a full
//   poll cycle.
// - Backoff: healthy → poll every 120s. Unhealthy → poll every 30s so the
//   banner clears quickly once the backend is back.
// - 2s timeout per attempt, built on AbortController rather than
//   AbortSignal.timeout so older Safari (< 16.4) works too.
// - Defensive parsing: we only look at `res.ok`; any body shape is fine.

import { useQuery } from "@tanstack/react-query";
import { SSE_BASE_URL } from "@/lib/constants";

const SAME_ORIGIN_URL = "/api/v1/health";
const DIRECT_URL = SSE_BASE_URL ? `${SSE_BASE_URL}/api/v1/health` : null;
const FETCH_TIMEOUT_MS = 2_000;
const RETRY_DELAY_MS = 1_200;
const HEALTHY_POLL_MS = 120_000;
export const UNHEALTHY_POLL_MS = 30_000;

function fetchWithTimeout(url: string): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  return fetch(url, { signal: controller.signal, cache: "no-store" }).finally(() =>
    clearTimeout(timer),
  );
}

async function probe(url: string): Promise<boolean> {
  try {
    const res = await fetchWithTimeout(url);
    return res.ok;
  } catch {
    return false;
  }
}

async function probeCycle(): Promise<boolean> {
  // Same-origin first (mirrors how the app's real traffic flows); the direct
  // backend URL is the fallback for a degraded proxy layer.
  if (await probe(SAME_ORIGIN_URL)) return true;
  if (DIRECT_URL) return probe(DIRECT_URL);
  return false;
}

async function probeHealth(): Promise<boolean> {
  if (await probeCycle()) return true;
  // One real retry so a single transient blip — DNS hiccup, cold edge, a
  // brief provider 5xx window — doesn't light up the banner for a full cycle.
  await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
  return probeCycle();
}

export function useHealthCheck() {
  return useQuery({
    queryKey: ["backend-health"],
    queryFn: probeHealth,
    // Poll faster while unhealthy so the banner clears quickly; slower while
    // green to keep request volume low.
    refetchInterval: (query) => (query.state.data === false ? UNHEALTHY_POLL_MS : HEALTHY_POLL_MS),
    refetchIntervalInBackground: false,
    retry: 1, // safety net if probeHealth ever throws unexpectedly
    staleTime: 15_000,
  });
}
