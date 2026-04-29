"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSampleQuestions } from "@/hooks/use-sample-questions";

interface RegenerateButtonProps {
  dbId: string | undefined;
  className?: string;
}

export function RegenerateButton({ dbId, className }: RegenerateButtonProps) {
  const { data, regenerate } = useSampleQuestions(dbId);
  const isPending = !data || data.status === "pending";
  const isLoading = regenerate.isPending;

  return (
    <Button
      variant="ghost"
      size="sm"
      className={className}
      onClick={() => regenerate.mutate()}
      disabled={isPending || isLoading || !dbId}
      title="Regenerate sample questions"
    >
      <RefreshCw className={`size-3 mr-1 ${isLoading ? "animate-spin" : ""}`} />
      Regenerate
    </Button>
  );
}
