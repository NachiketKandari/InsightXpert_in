"use client";

// Overview tab: 6 aggregate cards + a compact 7-day chats sparkline.
// No chart library — raw SVG is fine for a tiny widget.

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useAdminFeatures } from "@/hooks/use-admin-features";
import { useAdminOverview } from "@/hooks/use-admin-overview";
import { FeatureTogglesEditor } from "@/components/admin/feature-toggles";
import { apiCall } from "@/lib/api";
import type { FeatureToggles } from "@/types/admin";

function Card({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Sparkline({ points }: { points: { day: number; chats: number }[] }) {
  if (points.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">No activity in the past 7 days.</p>
    );
  }
  const width = 320;
  const height = 64;
  const pad = 4;
  const max = Math.max(1, ...points.map((p) => p.chats));
  const n = points.length;
  const stepX = n === 1 ? 0 : (width - pad * 2) / (n - 1);
  const coords = points.map((p, i) => {
    const x = pad + i * stepX;
    const y = pad + (height - pad * 2) * (1 - p.chats / max);
    return [x, y] as const;
  });
  const path = coords
    .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
    .join(" ");
  const areaPath = `${path} L${coords[coords.length - 1][0].toFixed(1)},${height - pad} L${coords[0][0].toFixed(1)},${height - pad} Z`;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label={`Chats per day, last ${n} days, max ${max}`}
      className="text-primary"
    >
      <path d={areaPath} fill="currentColor" opacity={0.12} />
      <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} />
      {coords.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={2} fill="currentColor" />
      ))}
    </svg>
  );
}

export default function OverviewPage() {
  const { data, isLoading, error } = useAdminOverview();
  const { data: featuresData, isLoading: featuresLoading } = useAdminFeatures();

  // Sync React Query data to local state for optimistic mutation updates
  const [features, setFeatures] = useState<FeatureToggles | null>(null);
  useEffect(() => {
    if (featuresData?.features) {
      setFeatures(featuresData.features);
    }
  }, [featuresData]);

  const handleFeaturesChange = useCallback(async (next: FeatureToggles) => {
    setFeatures(next); // optimistic
    // Find which key changed and persist
    for (const key of Object.keys(next) as (keyof FeatureToggles)[]) {
      if (features && next[key] !== features[key]) {
        const ok = await apiCall(
          `/api/v1/config/features`,
          {
            method: "POST",
            body: JSON.stringify({ feature: key, enabled: next[key] }),
          },
        );
        if (!ok) {
          toast.error(`Failed to toggle ${key}`);
          setFeatures(features); // revert
          return;
        }
      }
    }
  }, [features]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Failed to load overview.
      </div>
    );
  }

  const thumbsRatio =
    data.thumbs_ratio_7d === null
      ? "—"
      : `${Math.round(data.thumbs_ratio_7d * 100)}%`;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Card label="Active users (24h)" value={data.active_users_24h.toLocaleString()} />
        <Card label="Total users" value={data.total_users.toLocaleString()} />
        <Card label="Chats (24h)" value={data.chats_today.toLocaleString()} />
        <Card label="Tokens (24h)" value={data.tokens_today.toLocaleString()} />
        <Card label="Thumbs up (7d)" value={thumbsRatio} hint="Of rated turns" />
        <Card
          label="Sparkline"
          value={data.sparkline_7d
            .reduce((s, p) => s + p.chats, 0)
            .toLocaleString()}
          hint="Chats last 7 days"
        />
      </div>
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-medium">Chats — last 7 days</h2>
        </div>
        <Sparkline
          points={data.sparkline_7d.map((p) => ({ day: p.day, chats: p.chats }))}
        />
      </div>

      {!featuresLoading && features && (
        <div className="rounded-lg border border-border bg-card p-4">
          <FeatureTogglesEditor
            features={features}
            onChange={handleFeaturesChange}
          />
        </div>
      )}
    </div>
  );
}
