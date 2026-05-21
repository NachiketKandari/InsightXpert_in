"use client";

import { Loader2 } from "lucide-react";

interface GenerationProgressProps {
  progress: { current: number; total: number } | null;
}

export function GenerationProgress({ progress }: GenerationProgressProps) {
  const pct =
    progress && progress.total > 0
      ? Math.round((progress.current / progress.total) * 100)
      : 0;
  const hasProgress = progress !== null && progress.current > 0;

  return (
    <div className="flex flex-col items-center gap-2 w-full max-w-xs">
      <div className="h-1 w-full bg-muted rounded-full overflow-hidden">
        {hasProgress ? (
          <div
            className="h-full bg-primary rounded-full transition-all duration-500 ease-out"
            style={{ width: `${Math.max(pct, 10)}%` }}
          />
        ) : (
          <div className="h-full w-1/3 bg-primary rounded-full animate-pulse" />
        )}
      </div>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" />
        {hasProgress
          ? `Generating sample questions (${progress!.current}/${progress!.total})…`
          : "Generating sample questions…"}
      </span>
    </div>
  );
}
