"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useCurrentUser } from "@/hooks/use-current-user";

function AppSkeleton() {
  return (
    <div className="flex h-screen bg-background">
      {/* Left sidebar skeleton */}
      <aside className="hidden w-64 shrink-0 border-r border-border md:flex flex-col">
        <div className="flex items-center gap-2 px-4 h-14 border-b border-border">
          <div className="size-6 rounded bg-muted/60 animate-pulse" />
          <div className="h-4 w-24 rounded bg-muted/60 animate-pulse" />
        </div>
        <div className="flex flex-col gap-0.5 p-2 mt-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="px-3 py-3">
              <div
                className="h-4 animate-pulse rounded bg-muted/60"
                style={{ width: `${60 + Math.sin(i * 1.7) * 30}%` }}
              />
            </div>
          ))}
        </div>
      </aside>

      {/* Main content skeleton */}
      <main className="flex-1 flex flex-col">
        {/* Header skeleton */}
        <header className="flex items-center justify-between px-4 h-14 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="size-8 rounded bg-muted/60 animate-pulse md:hidden" />
            <div className="h-5 w-32 rounded bg-muted/60 animate-pulse" />
          </div>
          <div className="flex items-center gap-2">
            <div className="size-8 rounded bg-muted/60 animate-pulse" />
            <div className="size-8 rounded bg-muted/60 animate-pulse" />
            <div className="size-8 rounded-full bg-muted/60 animate-pulse" />
          </div>
        </header>

        {/* Content area skeleton */}
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-4">
            <div className="size-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <p className="text-sm text-muted-foreground">Loading your workspace…</p>
          </div>
        </div>
      </main>
    </div>
  );
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useCurrentUser();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      const next = encodeURIComponent(
        typeof window !== "undefined"
          ? window.location.pathname + window.location.search
          : "/",
      );
      router.replace(`/login?next=${next}`);
    }
  }, [isLoading, user, router]);

  if (isLoading || !user) {
    // Show full-page skeleton while auth resolves instead of a blank
    // white screen. On a cold load /auth/me takes 700ms+ — the skeleton
    // gives immediate visual feedback that the app is loading.
    if (isLoading) return <AppSkeleton />;
    return null; // redirect pending — flash of nothing is brief
  }
  return <>{children}</>;
}
