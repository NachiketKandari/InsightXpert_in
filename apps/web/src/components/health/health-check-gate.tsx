"use client";

// Backend-unavailable banner — modeled after public/InsightXpert's health
// pattern, but less disruptive. Public redirects to a static /503.html on the
// first probe failure (full-page takeover). We prefer a sticky top banner so
// devs can keep seeing the app while the backend bounces.
//
// Trade-offs (Step 4 of the fix brief):
// - We poll /api/v1/health every 30s when green, 15s when red (see
//   use-health-check.ts). That keeps ECONNREFUSED noise in the Next dev
//   terminal to occasional probes instead of every-request retries.
// - A 3s initial grace window avoids flashing the banner during hot reload /
//   cold start when the first probe hasn't resolved yet.

import { useEffect, useState } from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import { useHealthCheck } from "@/hooks/use-health-check";
import { Button } from "@/components/ui/button";

const GRACE_MS = 3_000;

export function HealthCheckGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading, isFetching, refetch } = useHealthCheck();
  const [showAfterGrace, setShowAfterGrace] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setShowAfterGrace(true), GRACE_MS);
    return () => clearTimeout(t);
  }, []);

  // Only surface the banner once (a) the grace window elapsed, (b) the first
  // probe finished, and (c) the last probe returned false.
  const unavailable = showAfterGrace && !isLoading && data === false;

  return (
    <>
      {unavailable ? (
        <div
          role="alert"
          aria-live="polite"
          className="sticky top-0 z-50 w-full border-b border-amber-500/40 bg-amber-500/15 text-amber-900 backdrop-blur supports-[backdrop-filter]:bg-amber-500/15 dark:text-amber-100"
        >
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2 text-sm">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            <span className="flex-1">
              <strong className="font-semibold">Backend unavailable.</strong>{" "}
              Retrying every 15s. Some actions will fail until it&apos;s back.
            </span>
            {isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-label="Retrying" />
            ) : null}
            <Button
              size="sm"
              variant="outline"
              className="h-7"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              Retry now
            </Button>
          </div>
        </div>
      ) : null}
      {children}
    </>
  );
}
