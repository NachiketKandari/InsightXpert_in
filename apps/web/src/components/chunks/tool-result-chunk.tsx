"use client";

import React, { useState, useMemo } from "react";
import { ChevronRight, Table2 } from "lucide-react";
import type { ChatChunk } from "@/types/chat";
import { parseToolResult } from "@/lib/chunk-parser";
import { DataTable } from "./data-table";
import { useChatStore } from "@/stores/chat-store";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

interface ToolResultChunkProps {
  chunk: ChatChunk;
  /** Pre-parsed result from parent to avoid double JSON.parse. */
  parsedData?: { columns: string[]; rows: Record<string, unknown>[]; rowCount: number } | null;
  /**
   * Owning assistant message id. Used to subscribe to citation highlights
   * scoped to this message; clicks on `[^N]` footnotes in the answer above
   * dispatch a highlight that addresses this messageId, and we flash the
   * cited rows in our DataTable.
   */
  messageId?: string;
}

/** Derive a human-readable badge label from the tool name. */
function toolBadgeLabel(toolName?: string): string {
  if (!toolName || toolName === "run_sql") return "Query Results";
  return toolName
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const ToolResultChunkInner = function ToolResultChunk({ chunk, parsedData, messageId }: ToolResultChunkProps) {
  const parsed = useMemo(
    () => parsedData !== undefined ? parsedData : parseToolResult(chunk),
    [chunk, parsedData],
  );
  const isAdvanced = chunk.data?.agent === "advanced" || chunk.data?.agent === "statistician" || chunk.data?.agent === "quant_analyst";
  const [open, setOpen] = useState(!isAdvanced);

  // Subscribe to citation highlights scoped to this message. When a [^N]
  // footnote in the answer above is clicked, the store records which row
  // indices to flash; we forward them to DataTable.
  const highlight = useChatStore((s) => s.messageHighlight);
  const isOurHighlight =
    highlight != null && messageId != null && highlight.messageId === messageId;
  const highlightedRowIndices = isOurHighlight ? highlight.rowIndices : undefined;
  const highlightTs = isOurHighlight ? highlight.ts : null;

  // Auto-expand the table when a citation in our message is clicked, so the
  // user actually sees the row that was highlighted.
  React.useEffect(() => {
    if (isOurHighlight && !open) setOpen(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightTs]);

  if (!parsed) {
    const raw =
      typeof chunk.data?.result === "string"
        ? chunk.data.result
        : JSON.stringify(chunk.data, null, 2);

    return (
      <pre className="text-xs text-muted-foreground bg-muted/30 rounded-lg p-3 font-mono overflow-x-auto">
        {raw}
      </pre>
    );
  }

  const label = toolBadgeLabel(chunk.tool_name ?? chunk.data?.tool as string | undefined);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border border-border bg-card/50 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-2 w-full px-3 py-2 hover:bg-accent/30 transition-colors text-left">
            <ChevronRight
              className={cn(
                "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                open && "rotate-90"
              )}
            />
            <Table2 className="size-4 shrink-0 text-muted-foreground" />
            <Badge variant="secondary" className="text-xs">
              {label}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {parsed.rowCount} row{parsed.rowCount !== 1 ? "s" : ""}
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 border-t border-border/50 pt-3">
            <DataTable
              columns={parsed.columns}
              rows={parsed.rows}
              highlightedRowIndices={highlightedRowIndices}
              highlightTs={highlightTs}
            />
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
};

export const ToolResultChunk = React.memo(ToolResultChunkInner);
