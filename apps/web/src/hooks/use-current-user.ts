// apps/web/src/hooks/use-current-user.ts
// One place every component reads identity from. Cached via TanStack Query;
// null means unauth. Errors throw so they propagate to error boundaries.

"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchMe, type CurrentUser } from "@/lib/auth-api";

export function useCurrentUser(): {
  user: CurrentUser | null;
  isLoading: boolean;
  isAdmin: boolean;
  refetch: () => void;
} {
  const q = useQuery({
    queryKey: ["current-user"],
    queryFn: fetchMe,
    staleTime: 300_000,
    retry: false,
  });
  return {
    user: q.data ?? null,
    isLoading: q.isLoading,
    isAdmin: q.data?.role === "admin",
    refetch: () => { void q.refetch(); },
  };
}
