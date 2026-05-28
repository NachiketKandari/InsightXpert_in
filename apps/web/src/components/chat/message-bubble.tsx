"use client";

import React, { useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion } from "framer-motion";
import { Loader2, Zap } from "lucide-react";
import { ChunkRenderer } from "@/components/chunks/chunk-renderer";
import { ProcessGroup } from "@/components/chunks/process-group";
import { MessageActions } from "@/components/chat/message-actions";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useChatStore } from "@/stores/chat-store";
import { useCurrentUser } from "@/hooks/use-current-user";
import type { Message, EnrichmentTrace, OrchestratorPlan, AgentTrace, ChatChunk } from "@/types/chat";
import { downloadMessageReport, downloadConversationReport } from "@/lib/export-report";

// Chunk types whose UI renderers care about an "is this stage finished?" hint.
// A chunk is considered complete when a later chunk has arrived, or when the
// overall stream has ended. Other chunk types render statically and do not
// need the hint (they pass undefined).
const COMPLETABLE_CHUNK_TYPES = new Set<string>([
  "status",
  "tool_call",
  "answer",
  "sql_executing", // bug fix 2026-05-01: was missing → spinner never stopped
]);

const MILESTONE_CHUNK_TYPES = new Set<string>([
  "sql_generated",
  "sql", // legacy
  "tool_result",
  "rows_returned",
  "answer",
  "answer_delta",
  "insight",
  "answer_generated",
  "error",
  "clarification",
]);

const MessageMetrics = React.memo(function MessageMetrics({ message }: { message: Message }) {
  const { wallTimeMs, generationTimeMs, inputTokens, outputTokens } = message;
  if (!wallTimeMs && !generationTimeMs && !inputTokens && !outputTokens) return null;

  // Prefer wall-clock time (click→done) over server-only generation time.
  const displayMs = wallTimeMs ?? generationTimeMs;
  const timeSec = displayMs != null ? (displayMs / 1000).toFixed(1) : null;
  const timeTooltip = wallTimeMs != null ? "Total response time (click → done)" : "Server generation time";
  const fmt = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  const fmtFull = (n: number) => n.toLocaleString();

  return (
    <div className="flex items-center gap-2.5 text-[11px] text-muted-foreground/75 select-none mt-0.5">
      {timeSec && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-default">{timeSec}s</span>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            {timeTooltip}: {timeSec}s
          </TooltipContent>
        </Tooltip>
      )}
      {(inputTokens != null || outputTokens != null) && timeSec && (
        <span className="opacity-60">·</span>
      )}
      {inputTokens != null && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-default">↑{fmt(inputTokens)}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Input tokens: {fmtFull(inputTokens)}
          </TooltipContent>
        </Tooltip>
      )}
      {inputTokens != null && outputTokens != null && (
        <span className="opacity-60">·</span>
      )}
      {outputTokens != null && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-default">↓{fmt(outputTokens)}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            Output tokens: {fmtFull(outputTokens)}
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
});

const selectIsActiveStreaming = (s: { isStreaming: boolean; streamingConversationId: string | null; activeConversationId: string | null }) =>
  s.isStreaming && s.streamingConversationId === s.activeConversationId;

interface MessageBubbleProps {
  message: Message;
  isLastAssistant?: boolean;
  onRetry?: () => void;
  /** Re-send a user message as a new message at the bottom */
  onResend?: (content: string) => void;
  // Takes messageId so callers can pass a stable handler without wrapping in
  // a per-message closure, which would break React.memo's prop comparison.
  onFeedback?: (messageId: string, type: "up" | "down", comment?: string) => void;
  onMarkInsight?: (messageId: string, note?: string) => Promise<boolean>;
  readOnly?: boolean;
}

function MessageBubbleInner({
  message,
  isLastAssistant,
  onRetry,
  onResend,
  onFeedback,
  onMarkInsight,
  readOnly = false,
}: MessageBubbleProps) {
  const isStreaming = useChatStore(selectIsActiveStreaming);
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const { isAdmin } = useCurrentUser();
  const isUser = message.role === "user";

  // Stable wrapper so MessageActions always gets the same function reference
  // (message.id is a UUID and never changes; onFeedback is stable from parent).
  const handleFeedbackForMsg = useCallback(
    (type: "up" | "down", comment?: string) => onFeedback?.(message.id, type, comment),
    [message.id, onFeedback],
  );

  const handleMarkInsightForMsg = useCallback(
    (note?: string): Promise<boolean> =>
      onMarkInsight ? onMarkInsight(message.id, note) : Promise.resolve(false),
    [message.id, onMarkInsight],
  );

  const enrichmentTraces = useMemo<EnrichmentTrace[]>(() => {
    if (!message.chunks?.length) return [];
    return message.chunks
      .filter((c) => c.type === "enrichment_trace" && c.data)
      .map((c) => c.data as unknown as EnrichmentTrace)
      .sort((a, b) => a.source_index - b.source_index);
  }, [message.chunks]);

  const orchestratorPlan = useMemo<OrchestratorPlan | null>(() => {
    if (!message.chunks?.length) return null;
    const planChunk = message.chunks.find((c) => c.type === "orchestrator_plan" && c.data);
    if (!planChunk?.data) return null;
    return planChunk.data as unknown as OrchestratorPlan;
  }, [message.chunks]);

  const agentTraces = useMemo<AgentTrace[]>(() => {
    if (!message.chunks?.length) return [];
    return message.chunks
      .filter((c) => c.type === "agent_trace" && c.data)
      .map((c) => c.data as unknown as AgentTrace);
  }, [message.chunks]);

  // Show "Create Automation" for admin, assistant messages with tool_result, and not streaming
  const hasToolResult = !isUser && message.chunks.some((c) => c.type === "tool_result");
  const showAutomationBtn = isAdmin && hasToolResult && !isStreaming;

  const handleDownloadMessage = useCallback(() => {
    const conv = useChatStore.getState().activeConversation();
    if (!conv) return;
    const msgs = conv.messages;
    const idx = msgs.findIndex((m) => m.id === message.id);
    const userQ =
      idx > 0 && msgs[idx - 1].role === "user" ? msgs[idx - 1].content : undefined;
    downloadMessageReport(message, userQ, conv.title);
  }, [message]);

  const handleDownloadConversation = useCallback(() => {
    const conv = useChatStore.getState().activeConversation();
    if (!conv) return;
    downloadConversationReport(conv);
  }, []);

  const handleCreateAutomation = useCallback(() => {
    if (!activeConversationId) return;
    // Phase C1: workflow-canvas builder is deferred to C2. For now, we
    // route the user to the Automations list page where the form-based
    // "New automation" dialog lives. The message + conversation context
    // is preserved in the URL query so a future builder can rehydrate it.
    const params = new URLSearchParams({
      conversationId: activeConversationId,
      messageId: message.id,
    });
    if (typeof window !== "undefined") {
      window.location.href = `/automations?${params.toString()}`;
    }
  }, [message.id, activeConversationId]);

  const renderedItems = useMemo(() => {
    if (!message.chunks?.length) return [];

    type RenderItem =
      | { type: "milestone"; chunk: ChatChunk; index: number }
      | { type: "process_group"; chunks: { chunk: ChatChunk; index: number }[] };

    const items: RenderItem[] = [];
    let currentGroup: { chunk: ChatChunk; index: number }[] = [];

    message.chunks.forEach((chunk, index) => {
      const isProcess = !MILESTONE_CHUNK_TYPES.has(chunk.type);
      if (isProcess) {
        currentGroup.push({ chunk, index });
      } else {
        if (currentGroup.length > 0) {
          items.push({ type: "process_group", chunks: currentGroup });
          currentGroup = [];
        }
        items.push({ type: "milestone", chunk, index });
      }
    });

    if (currentGroup.length > 0) {
      items.push({ type: "process_group", chunks: currentGroup });
    }

    return items;
  }, [message.chunks]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={`group/message flex flex-col ${isUser ? "items-end" : "items-start"}`}
    >
      {isUser ? (
        <div className="max-w-[90%] sm:max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-3 sm:px-4 py-2 sm:py-2.5 text-sm text-primary-foreground">
          {message.content}
        </div>
      ) : (
        <div className="w-full space-y-3">
          {message.chunks.length > 0 ? (
            <>
              {renderedItems.map((item, i) => {
                if (item.type === "milestone") {
                  const completable = COMPLETABLE_CHUNK_TYPES.has(item.chunk.type);
                  return (
                    <ChunkRenderer
                      key={`milestone-${item.index}`}
                      chunk={item.chunk}
                      isComplete={
                        completable
                          ? item.index < message.chunks.length - 1 || !isStreaming
                          : undefined
                      }
                      isStreaming={isStreaming && !!isLastAssistant}
                      enrichmentTraces={enrichmentTraces}
                      orchestratorPlan={orchestratorPlan}
                      agentTraces={agentTraces}
                      messageId={message.id}
                    />
                  );
                } else {
                  const lastInGroupIdx = item.chunks[item.chunks.length - 1].index;
                  return (
                    <ProcessGroup
                      key={`group-${item.chunks[0].index}`}
                      chunks={item.chunks}
                      isStreaming={isStreaming}
                      isLastAssistant={!!isLastAssistant && lastInGroupIdx === message.chunks.length - 1}
                      enrichmentTraces={enrichmentTraces}
                      orchestratorPlan={orchestratorPlan}
                      agentTraces={agentTraces}
                      messageId={message.id}
                    />
                  );
                }
              })}
              {isStreaming && isLastAssistant && (() => {
                const last = message.chunks[message.chunks.length - 1];
                if (last?.type === "answer" || last?.type === "answer_generated" || last?.type === "error") return null;
                if (last && !MILESTONE_CHUNK_TYPES.has(last.type)) return null;
                return (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.2 }}
                    className="flex items-center gap-2 text-sm text-muted-foreground py-1"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-accent shrink-0" />
                    <span>Processing&hellip;</span>
                  </motion.div>
                );
              })()}
            </>
          ) : isStreaming && isLastAssistant ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-1">
              <Loader2 className="h-4 w-4 animate-spin text-cyan-accent" />
              <span>Thinking&hellip;</span>
            </div>
          ) : message.content ? (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          ) : null}
        </div>
      )}

      {!isUser && <MessageMetrics message={message} />}

      {message.content && !readOnly && (
        <MessageActions
          role={message.role}
          content={message.content}
          timestamp={message.timestamp}
          isLastAssistant={isLastAssistant}
          onRetry={onRetry}
          onResend={isUser ? onResend : undefined}
          onFeedback={handleFeedbackForMsg}
          onMarkInsight={!isUser ? handleMarkInsightForMsg : undefined}
          onDownloadMessage={!isUser ? handleDownloadMessage : undefined}
          onDownloadConversation={!isUser ? handleDownloadConversation : undefined}
        />
      )}

      {/* TODO(deferred-features): Automations hidden until backend lands — see docs/deferred-features.md#automations */}
      {false && showAutomationBtn && (
        <button
          onClick={handleCreateAutomation}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary transition-colors mt-1"
        >
          <Zap className="size-3.5" />
          <span>Create Automation</span>
        </button>
      )}
    </motion.div>
  );
}

// Note: isStreaming comes from useChatStore inside the component, so Zustand's
// subscription can trigger re-renders independently of this comparator.
// The memo prevents re-renders from parent list changes (sibling messages).
export const MessageBubble = React.memo(MessageBubbleInner, (prev, next) => {
  return (
    prev.message === next.message &&
    prev.isLastAssistant === next.isLastAssistant &&
    prev.onRetry === next.onRetry &&
    prev.onResend === next.onResend &&
    prev.onFeedback === next.onFeedback &&
    prev.onMarkInsight === next.onMarkInsight &&
    prev.readOnly === next.readOnly
  );
});
