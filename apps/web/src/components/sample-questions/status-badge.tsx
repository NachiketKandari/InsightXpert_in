"use client";

import { Badge } from "@/components/ui/badge";
import { useSampleQuestions } from "@/hooks/use-sample-questions";
import type { SampleQuestionsStatus } from "@/types/sample-questions";

const LABELS: Record<SampleQuestionsStatus, string> = {
  ok: "Tailored",
  fallback: "Auto-generated",
  pending: "Generating…",
  failed: "Failed",
};

interface StatusBadgeProps {
  dbId: string | undefined;
  className?: string;
}

export function StatusBadge({ dbId, className }: StatusBadgeProps) {
  const { data } = useSampleQuestions(dbId);
  if (!data) return null;

  return (
    <Badge
      variant={data.status === "failed" ? "destructive" : "secondary"}
      className={className}
    >
      {LABELS[data.status]}
    </Badge>
  );
}
