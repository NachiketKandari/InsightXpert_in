"use client";

import {
  CheckCircle2,
  Circle,
  Loader2,
  MinusCircle,
  XCircle,
} from "lucide-react";

import type { ProfileStep } from "@/hooks/useProfileRun";

const STAGE_LABELS: Record<ProfileStep["stage"], string> = {
  schema: "Schema extraction",
  stats: "Column statistics",
  join_graph: "FK & join discovery",
  summaries: "LLM summaries",
  quirks: "LLM quirk detection",
  lsh: "LSH index",
  vectors: "Embedding vectors",
  table_descriptions: "Table descriptions",
};

export function ProfileStepRow({ step }: { step: ProfileStep }) {
  const label = STAGE_LABELS[step.stage];

  let icon: React.ReactNode;
  let detail: string | null = null;
  let tone = "";

  switch (step.state) {
    case "pending":
      icon = <Circle className="size-4 text-muted-foreground/50" />;
      break;
    case "running":
      icon = <Loader2 className="size-4 animate-spin text-primary" />;
      if (step.batchTotal && step.batchTotal > 0) {
        detail = `batch ${step.batchIndex}/${step.batchTotal}`;
      }
      break;
    case "done":
      icon = <CheckCircle2 className="size-4 text-emerald-500" />;
      if (step.durationMs != null) {
        detail = formatDuration(step.durationMs);
      }
      tone = "text-foreground";
      break;
    case "skipped":
      icon = <MinusCircle className="size-4 text-muted-foreground" />;
      detail = step.note ?? "skipped";
      tone = "text-muted-foreground";
      break;
    case "error":
      icon = <XCircle className="size-4 text-red-500" />;
      detail = step.note?.replace(/^failed:\s*/, "") ?? null;
      tone = "text-red-600 dark:text-red-400";
      break;
  }

  return (
    <li className="flex items-center gap-3 py-2">
      <span className="flex size-5 items-center justify-center">{icon}</span>
      <span className={`flex-1 text-sm ${tone}`}>{label}</span>
      {detail && (
        <span className="text-xs text-muted-foreground font-mono">{detail}</span>
      )}
    </li>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}
