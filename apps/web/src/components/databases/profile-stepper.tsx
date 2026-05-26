"use client";

import { Clock } from "lucide-react";
import { ProfileStepRow } from "./profile-step-row";
import type { ProfileStep } from "@/hooks/useProfileRun";

interface ProfileStepperProps {
  steps: ProfileStep[];
  totalDurationMs?: number | null;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

export function ProfileStepper({ steps, totalDurationMs }: ProfileStepperProps) {
  return (
    <ol className="divide-y divide-border rounded-md border border-border">
      {steps.map((step) => (
        <div key={step.stage} className="px-3">
          <ProfileStepRow step={step} />
        </div>
      ))}
      {totalDurationMs != null && totalDurationMs > 0 && (
        <div className="flex items-center gap-3 px-3 py-2">
          <Clock className="size-4 text-muted-foreground" />
          <span className="flex-1 text-sm font-medium text-muted-foreground">
            Total
          </span>
          <span className="text-xs text-muted-foreground font-mono">
            {formatDuration(totalDurationMs)}
          </span>
        </div>
      )}
    </ol>
  );
}
