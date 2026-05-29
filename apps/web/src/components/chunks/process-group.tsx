"use client";

import React, { useState, useEffect } from "react";
import { ChevronRight, Loader2, CheckCircle } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { ChatChunk, EnrichmentTrace, OrchestratorPlan, AgentTrace } from "@/types/chat";
import { ChunkRenderer } from "./chunk-renderer";

interface ProcessGroupProps {
  chunks: { chunk: ChatChunk; index: number }[];
  isStreaming: boolean;
  isLastAssistant: boolean;
  enrichmentTraces?: EnrichmentTrace[];
  orchestratorPlan?: OrchestratorPlan | null;
  agentTraces?: AgentTrace[];
  messageId?: string;
}

function getGroupTitle(chunks: { chunk: ChatChunk }[], isGroupActive: boolean): string {
  const types = chunks.map(c => c.chunk.type);
  
  if (types.includes("sql_executing")) {
    return isGroupActive ? "Executing SQL query..." : "SQL query executed";
  }
  if (types.some(t => ["schema_linking_started", "linked_schema_final", "candidate_sqls_generated", "literals_extracted", "semantic_matches", "join_paths_added"].includes(t))) {
    return isGroupActive ? "Analyzing database schema..." : "Analyzed database schema";
  }
  if (types.some(t => ["profile_stage_started", "profile_stage_completed", "profile_done", "profile_loaded"].includes(t))) {
    return isGroupActive ? "Profiling database..." : "Database profiling complete";
  }
  if (types.includes("few_shot_retrieved")) {
    return isGroupActive ? "Retrieving few-shot examples..." : "Retrieved few-shot examples";
  }
  if (types.includes("auto_routed")) {
    return isGroupActive ? "Routing request..." : "Routed request";
  }
  if (types.includes("stats_context")) {
    return isGroupActive ? "Retrieving dataset statistics..." : "Retrieved dataset statistics";
  }
  
  const last = chunks[chunks.length - 1]?.chunk;
  if (last?.type === "status") {
    const msg = (last.data?.message as string) ?? (last.data?.content as string) ?? last.content ?? "";
    if (msg) return msg;
  }
  if (last?.type === "tool_call") {
    return last.content ?? `Calling tool: ${last.tool_name ?? ""}`;
  }
  
  return isGroupActive ? "Thinking..." : "Thinking process";
}

export const ProcessGroup = React.memo(function ProcessGroup({
  chunks,
  isStreaming,
  isLastAssistant,
  enrichmentTraces,
  orchestratorPlan,
  agentTraces,
  messageId,
}: ProcessGroupProps) {
  const [open, setOpen] = useState(false);

  // If the last chunk of this group is the overall last chunk, and we are currently streaming
  const isGroupActive = isStreaming && isLastAssistant;

  const title = getGroupTitle(chunks, isGroupActive);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="w-full my-1.5">
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="flex items-center justify-between w-full px-3 py-2.5 hover:bg-accent/30 transition-colors text-left cursor-pointer select-none">
            <div className="flex items-center gap-2 min-w-0">
              {isGroupActive ? (
                <Loader2 className="size-3.5 animate-spin text-violet-500 shrink-0" />
              ) : (
                <CheckCircle className="size-3.5 text-emerald-500 shrink-0" />
              )}
              <span className="text-xs font-medium text-foreground/80 truncate">
                {title}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground shrink-0 pl-2">
              <span>
                {chunks.length} step{chunks.length === 1 ? "" : "s"}
              </span>
              <span className="opacity-40">·</span>
              <span>{open ? "Hide details" : "Show details"}</span>
              <ChevronRight
                className={cn(
                  "size-3.5 text-muted-foreground/60 transition-transform duration-200",
                  open && "rotate-90",
                )}
              />
            </div>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 pt-2.5 border-t border-border/50 bg-muted/5 space-y-2">
            <div className="border-l-2 border-primary/10 pl-3.5 space-y-2">
              {chunks.map(({ chunk, index }) => (
                <ChunkRenderer
                  key={index}
                  chunk={chunk}
                  isComplete={!isGroupActive}
                  isStreaming={isStreaming && isLastAssistant}
                  enrichmentTraces={enrichmentTraces}
                  orchestratorPlan={orchestratorPlan}
                  agentTraces={agentTraces}
                  messageId={messageId}
                />
              ))}
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
});
