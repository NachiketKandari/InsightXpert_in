"use client";

// TanStack Query wrapper over /api/v1/config/features.
// Backend sets Cache-Control: max-age=300; we mirror that as staleTime.

import { useQuery } from "@tanstack/react-query";

import { apiCall } from "@/lib/api";
import type { FeatureToggles } from "@/types/admin";

interface FeaturesResponse {
  features: FeatureToggles;
}

export function useAdminFeatures() {
  return useQuery({
    queryKey: ["admin", "features"],
    queryFn: () =>
      apiCall<FeaturesResponse>("/api/v1/config/features"),
    staleTime: 300_000,
  });
}
