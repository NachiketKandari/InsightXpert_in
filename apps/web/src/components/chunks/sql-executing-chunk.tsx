"use client";

import { Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { SqlExecutingData } from "@/types/chunks";

interface SqlExecutingChunkProps {
  data: SqlExecutingData;
  isComplete?: boolean;
}

/**
 * Tier-3: `sql_executing`. Visual analogue to "tool is running". Shows a
 * spinner plus a truncated preview of the SQL being executed.
 */
export function SqlExecutingChunk({ data, isComplete }: SqlExecutingChunkProps) {
  const preview = (data.sql ?? "").replace(/\s+/g, " ").trim();
  const truncated = preview.length > 120 ? `${preview.slice(0, 120)}…` : preview;

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-card/50 px-3 py-2">
      {isComplete ? (
        <Badge variant="secondary" className="text-[10px] font-normal">
          executed
        </Badge>
      ) : (
        <Loader2 className="size-3.5 shrink-0 animate-spin text-sky-500" />
      )}
      <span className="text-xs text-muted-foreground">Executing SQL</span>
      <code className="text-[11px] font-mono text-foreground/80 truncate min-w-0 flex-1">
        {truncated}
      </code>
    </div>
  );
}
