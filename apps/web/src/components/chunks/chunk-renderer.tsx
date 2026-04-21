"use client";

import React, { useState, useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import { CheckCircle, Loader2 } from "lucide-react";
import type { ChatChunk, EnrichmentTrace, OrchestratorPlan, AgentTrace } from "@/types/chat";
import { ThinkingTrace } from "./thinking-trace";
import { parseToolResult } from "@/lib/chunk-parser";
import { detectChartType } from "@/lib/chart-detector";
import { VALID_CHART_TYPES } from "@/lib/constants";
import { StatusChunk } from "./status-chunk";
import { ToolCallChunk } from "./tool-call-chunk";
import { SqlChunk } from "./sql-chunk";
import { ToolResultChunk } from "./tool-result-chunk";
import { ChartBlock } from "./chart-block";
import { AnswerChunk } from "./answer-chunk";
import { InsightChunk } from "./insight-chunk";
import { ErrorChunk } from "./error-chunk";
import { ClarificationChunk } from "./clarification-chunk";
import { StatsContextChunk } from "./stats-context-chunk";
import { ProfileLoadedChunk } from "./profile-loaded-chunk";
import {
  SchemaLinkingStartedChunk,
  CandidateSqlsChunk,
  LiteralsExtractedChunk,
  SemanticMatchesChunk,
  JoinPathsAddedChunk,
  LinkedSchemaFinalChunk,
} from "./schema-linking-chunk";
import { SqlGeneratedChunk } from "./sql-generated-chunk";
import { SqlExecutingChunk } from "./sql-executing-chunk";
import { RowsReturnedChunk } from "./rows-returned-chunk";
import { AnswerGeneratedChunk } from "./answer-generated-chunk";
import type {
  ProfileLoadedData,
  SchemaLinkingStartedData,
  CandidateSQLsGeneratedData,
  LiteralsExtractedData,
  SemanticMatchesData,
  JoinPathsAddedData,
  LinkedSchemaFinalData,
  SqlGeneratedData,
  SqlExecutingData,
  RowsReturnedData,
  AnswerGeneratedData,
} from "@/types/chunks";

/** Inline progress step: spinner → checkmark after a brief delay during streaming. */
function ProgressStep({ label, isComplete }: { label: string; isComplete?: boolean }) {
  const [timerDone, setTimerDone] = useState(false);
  const done = (isComplete ?? false) || timerDone;

  useEffect(() => {
    if (isComplete) return;
    const timer = setTimeout(() => setTimerDone(true), 600);
    return () => clearTimeout(timer);
  }, [isComplete]);

  return (
    <div className="flex items-center gap-2 text-muted-foreground text-sm py-1">
      {done ? (
        <CheckCircle className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
      ) : (
        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
      )}
      <span>{label}</span>
    </div>
  );
}

interface ChunkRendererProps {
  chunk: ChatChunk;
  isComplete?: boolean;
  /** When true, charts render eagerly (no IntersectionObserver). */
  isStreaming?: boolean;
  enrichmentTraces?: EnrichmentTrace[];
  orchestratorPlan?: OrchestratorPlan | null;
  agentTraces?: AgentTrace[];
}

function ChunkRendererInner({ chunk, isComplete, isStreaming, enrichmentTraces, orchestratorPlan, agentTraces }: ChunkRendererProps) {
  const parsed = useMemo(
    () => (chunk.type === "tool_result" ? parseToolResult(chunk) : null),
    [chunk],
  );
  const suggestedChartType = chunk.type === "tool_result"
    ? ((chunk.data?.visualization as string) ?? null)
    : null;
  const xColumn = chunk.type === "tool_result"
    ? ((chunk.data?.x_column as string) ?? undefined)
    : undefined;
  const yColumn = chunk.type === "tool_result"
    ? ((chunk.data?.y_column as string) ?? undefined)
    : undefined;

  const willShowChart = useMemo(() => {
    if (!parsed) return false;
    const ct =
      suggestedChartType && VALID_CHART_TYPES.has(suggestedChartType)
        ? suggestedChartType
        : detectChartType(parsed.columns, parsed.rows);
    return ct !== "none" && ct !== "table";
  }, [parsed, suggestedChartType]);

  let content: React.ReactNode;

  switch (chunk.type) {
    case "status": {
      const rawRag = chunk.data?.rag_context;
      const ragContext = Array.isArray(rawRag) ? (rawRag as string[]) : undefined;
      // Strict envelope: `data.message`. Legacy flat `content` kept as fallback.
      const msg = (chunk.data?.message as string | undefined) ?? chunk.content ?? "";
      content = <StatusChunk content={msg} isComplete={isComplete} ragContext={ragContext} />;
      break;
    }
    case "tool_call": {
      // Strict envelope: `data.tool`; legacy flat `tool_name` kept as fallback.
      const toolName =
        (chunk.data?.tool as string | undefined) ?? chunk.tool_name ?? undefined;
      const toolLabel =
        toolName === "run_sql"
          ? "Generating SQL query"
          : chunk.content ?? toolName ?? "";
      content = <ToolCallChunk content={toolLabel} isComplete={isComplete} />;
      break;
    }
    case "sql": {
      // Legacy Phase A shape — kept for back-compat with pre-B2 replay.
      const legacySql = chunk.sql ?? (chunk.data?.sql as string | undefined);
      content = legacySql ? <SqlChunk sql={legacySql} /> : null;
      break;
    }
    case "tool_result":
      content = (
        <>
          <ToolResultChunk chunk={chunk} parsedData={parsed} />
          {willShowChart && parsed && (
            <>
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              >
                <ProgressStep label="Creating visualization" />
              </motion.div>
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: "easeOut", delay: 0.7 }}
                className="mt-3"
              >
                <ChartBlock
                  columns={parsed.columns}
                  rows={parsed.rows}
                  suggestedChartType={suggestedChartType}
                  xColumn={xColumn}
                  yColumn={yColumn}
                  eager={isStreaming}
                />
              </motion.div>
            </>
          )}
        </>
      );
      break;
    case "answer": {
      // Legacy Phase A shape. Kept for back-compat.
      const legacyText =
        chunk.content ?? (chunk.data?.text as string | undefined) ?? "";
      content = (
        <>
          <ProgressStep label="Generating answer" isComplete={isComplete} />
          <AnswerChunk content={legacyText} />
        </>
      );
      break;
    }
    case "insight": {
      // Strict envelope: `data.content`; legacy flat `content` kept as fallback.
      const insightText =
        (chunk.data?.content as string | undefined) ?? chunk.content ?? "";
      content = (
        <>
          {orchestratorPlan && agentTraces && agentTraces.length > 0 && (
            <div className="mb-3">
              <ThinkingTrace plan={orchestratorPlan} traces={agentTraces} enrichmentTraces={enrichmentTraces} />
            </div>
          )}
          <ProgressStep label="Synthesized enriched insight" isComplete={isComplete} />
          {enrichmentTraces && enrichmentTraces.length > 0 ? (
            <InsightChunk content={insightText} traces={enrichmentTraces} />
          ) : (
            <AnswerChunk content={insightText} />
          )}
        </>
      );
      break;
    }
    case "orchestrator_plan":
      return null;
    case "agent_trace":
      return null;
    case "enrichment_trace":
      return null;
    case "error": {
      // Strict envelope: `data.detail` / `data.code`; legacy `content` fallback.
      const errText =
        (chunk.data?.detail as string | undefined) ??
        (chunk.data?.code as string | undefined) ??
        chunk.content ??
        "An error occurred";
      content = <ErrorChunk content={errText} />;
      break;
    }
    case "clarification": {
      // Strict envelope: `data.question`; legacy `content` fallback.
      const q =
        (chunk.data?.question as string | undefined) ??
        chunk.content ??
        "Could you clarify your question?";
      content = (
        <ClarificationChunk
          content={q}
          skipAllowed={!!(chunk.data?.skip_allowed)}
        />
      );
      break;
    }
    case "stats_context": {
      const sc = (chunk.data?.content as string | undefined) ?? chunk.content ?? "";
      content = (
        <>
          <ProgressStep label="Retrieved dataset statistics" isComplete={isComplete} />
          <StatsContextChunk
            content={sc}
            groups={chunk.data?.groups as string[]}
          />
        </>
      );
      break;
    }

    // -------------------------------------------------------------------
    // Tier-3: pipeline transparency
    // -------------------------------------------------------------------
    case "profile_loaded":
      content = (
        <ProfileLoadedChunk data={chunk.data as unknown as ProfileLoadedData} />
      );
      break;
    case "schema_linking_started":
      content = (
        <SchemaLinkingStartedChunk
          data={chunk.data as unknown as SchemaLinkingStartedData}
        />
      );
      break;
    case "candidate_sqls_generated":
      content = (
        <CandidateSqlsChunk
          data={chunk.data as unknown as CandidateSQLsGeneratedData}
        />
      );
      break;
    case "literals_extracted":
      content = (
        <LiteralsExtractedChunk
          data={chunk.data as unknown as LiteralsExtractedData}
        />
      );
      break;
    case "semantic_matches":
      content = (
        <SemanticMatchesChunk
          data={chunk.data as unknown as SemanticMatchesData}
        />
      );
      break;
    case "join_paths_added":
      content = (
        <JoinPathsAddedChunk
          data={chunk.data as unknown as JoinPathsAddedData}
        />
      );
      break;
    case "linked_schema_final":
      content = (
        <LinkedSchemaFinalChunk
          data={chunk.data as unknown as LinkedSchemaFinalData}
        />
      );
      break;
    case "sql_generated":
      content = (
        <SqlGeneratedChunk data={chunk.data as unknown as SqlGeneratedData} />
      );
      break;
    case "sql_executing":
      content = (
        <SqlExecutingChunk
          data={chunk.data as unknown as SqlExecutingData}
          isComplete={isComplete}
        />
      );
      break;
    case "rows_returned":
      content = (
        <RowsReturnedChunk data={chunk.data as unknown as RowsReturnedData} />
      );
      break;
    case "answer_generated":
      content = (
        <>
          <ProgressStep label="Generated answer" isComplete={isComplete} />
          <AnswerGeneratedChunk
            data={chunk.data as unknown as AnswerGeneratedData}
          />
        </>
      );
      break;

    // Tier-1: metrics is consumed upstream for stats; no renderer here.
    case "metrics":
      return null;

    default:
      content = null;
  }

  if (!content) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {content}
    </motion.div>
  );
}

export const ChunkRenderer = React.memo(ChunkRendererInner);
