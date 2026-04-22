"use client";

import { AlertTriangle } from "lucide-react";

import { PROFILING_MAX_COLUMNS_FOR_LLM } from "@/types/database";

interface AutoDisableWarningProps {
  columns: number | null;
}

export function AutoDisableWarning({ columns }: AutoDisableWarningProps) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-700 dark:text-amber-300">
      <AlertTriangle className="size-4 mt-0.5 shrink-0" />
      <div className="text-sm">
        <p className="font-medium">LLM stages auto-disabled</p>
        <p className="text-xs mt-0.5">
          {columns != null
            ? `This database has ${columns} columns, above the ${PROFILING_MAX_COLUMNS_FOR_LLM}-column cap.`
            : `This database is above the ${PROFILING_MAX_COLUMNS_FOR_LLM}-column cap.`}{" "}
          Summaries, quirks and vectors were skipped to keep costs bounded.
        </p>
      </div>
    </div>
  );
}
