"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, Table2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { DataTable } from "./data-table";
import type { RowsReturnedData } from "@/types/chunks";

interface RowsReturnedChunkProps {
  data: RowsReturnedData;
}

/**
 * Tier-3: `rows_returned`. Replaces `tool_result` for `run_sql`. Rows may
 * arrive as list[list] (array-of-cells, column-aligned) or list[dict]; we
 * normalize to list[dict] for `DataTable`.
 */
function RowsReturnedChunkInner({ data }: RowsReturnedChunkProps) {
  const [open, setOpen] = useState(true);

  const dictRows = useMemo<Record<string, unknown>[]>(() => {
    const raw = data.rows ?? [];
    const cols = data.columns ?? [];
    if (raw.length === 0) return [];

    const first = raw[0];
    // Already list[dict]
    if (first && typeof first === "object" && !Array.isArray(first)) {
      return raw as Record<string, unknown>[];
    }
    // list[list] — zip with columns
    return (raw as unknown[][]).map((row) => {
      const obj: Record<string, unknown> = {};
      cols.forEach((col, i) => {
        obj[col] = row?.[i];
      });
      return obj;
    });
  }, [data.rows, data.columns]);

  const columns = data.columns ?? [];
  const rowCount = data.row_count ?? dictRows.length;
  const execMs = data.execution_time_ms;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border border-border bg-card/50 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-2 w-full px-3 py-2 hover:bg-accent/30 transition-colors text-left">
            <ChevronRight
              className={cn(
                "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                open && "rotate-90",
              )}
            />
            <Table2 className="size-4 shrink-0 text-muted-foreground" />
            <Badge variant="secondary" className="text-xs">
              Query Results
            </Badge>
            <span className="text-xs text-muted-foreground">
              {rowCount} row{rowCount === 1 ? "" : "s"}
            </span>
            {typeof execMs === "number" && (
              <Badge variant="outline" className="text-[10px] font-normal ml-auto">
                {execMs} ms
              </Badge>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 border-t border-border/50 pt-3">
            {dictRows.length > 0 ? (
              <DataTable columns={columns} rows={dictRows} />
            ) : (
              <p className="text-xs text-muted-foreground italic">
                No rows returned.
              </p>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

export const RowsReturnedChunk = React.memo(RowsReturnedChunkInner);
