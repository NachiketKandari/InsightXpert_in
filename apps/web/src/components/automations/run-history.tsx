"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { useAutomationRuns } from "@/hooks/use-automation-runs";
import { STATUS_VARIANT } from "@/lib/automation-utils";
import { RunDetailModal } from "./run-detail-modal";
import type { AutomationRun } from "@/types/automation";

interface RunHistoryProps {
  automationId: string;
}

export function RunHistory({ automationId }: RunHistoryProps) {
  const { data: runs, isLoading, isError } = useAutomationRuns(automationId);
  const [selectedRun, setSelectedRun] = useState<AutomationRun | null>(null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary" />
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-sm text-red-600 dark:text-red-400 py-3 text-center">
        Failed to load run history.
      </p>
    );
  }

  if (!runs || runs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-3 text-center">
        No runs yet
      </p>
    );
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground">Time</th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground">Status</th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground">Rows</th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground">Duration</th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground">Triggers</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const firedCount = run.triggers_fired?.filter((t) => t.fired).length ?? 0;
              const totalCount = run.triggers_fired?.length ?? 0;
              return (
                <tr
                  key={run.id}
                  className="border-b border-border/50 last:border-0 hover:bg-muted/50 cursor-pointer transition-colors"
                  onClick={() => setSelectedRun(run)}
                >
                  <td className="px-3 py-2 text-xs">
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_VARIANT[run.status] ?? "secondary"} className="text-xs">
                      {run.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-xs">{run.row_count ?? "-"}</td>
                  <td className="px-3 py-2 text-xs">
                    {run.execution_time_ms != null ? `${run.execution_time_ms}ms` : "-"}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {totalCount > 0 ? `${firedCount}/${totalCount}` : "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <RunDetailModal
        run={selectedRun}
        open={selectedRun !== null}
        onOpenChange={(open) => !open && setSelectedRun(null)}
      />
    </>
  );
}
