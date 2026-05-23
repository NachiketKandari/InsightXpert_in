"use client";

import { useCallback, useMemo, memo } from "react";
import { toast } from "sonner";
import { useChatStore } from "@/stores/chat-store";
import { useInsightStore } from "@/stores/insight-store";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { MessageBubble } from "@/components/chat/message-bubble";
import { apiFetch } from "@/lib/api";

interface MessageListProps {
  onRetry?: (lastUserMessage: string) => void;
  readOnly?: boolean;
}

export const MessageList = memo(function MessageList({ onRetry, readOnly }: MessageListProps) {
  const conversation = useChatStore((s) => s.activeConversation());
  const messages = conversation?.messages ?? [];

  // Scroll only when the number of messages or streaming chunks changes —
  // NOT on every property update (feedback, tokens, wallTimeMs, etc.).
  const lastMsgChunkCount = messages.at(-1)?.chunks.length ?? 0;
  const { scrollRef, handleScroll } = useAutoScroll([messages.length, lastMsgChunkCount]);

  const lastUserMessage = useMemo(
    () => [...messages].reverse().find((m) => m.role === "user"),
    [messages],
  );

  const lastAssistantIdx = useMemo(
    () => messages.reduce((acc, msg, idx) => (msg.role === "assistant" ? idx : acc), -1),
    [messages],
  );

  const handleRetry = useCallback(() => {
    if (lastUserMessage && onRetry) {
      onRetry(lastUserMessage.content);
    }
  }, [lastUserMessage, onRetry]);

  const handleFeedback = useCallback(
    (messageId: string, type: "up" | "down", comment?: string) => {
      apiFetch("/api/v1/feedback", {
        method: "POST",
        body: JSON.stringify({
          message_id: messageId,
          feedback: type === "up",
          comment: comment || null,
        }),
      }).catch(() => {});
    },
    []
  );

  const handleMarkInsight = useCallback(
    (messageId: string, note?: string): Promise<boolean> => {
      // Optimistic: bump count immediately so the badge updates without
      // waiting for the POST → GET round-trip. Reconcile after POST succeeds.
      useInsightStore.getState().incrementCountOptimistic();
      return apiFetch("/api/v1/insights", {
        method: "POST",
        body: JSON.stringify({
          message_id: messageId,
          user_note: note || null,
        }),
      })
        .then((res) => {
          if (!res.ok) throw new Error("Failed to save insight");
          useInsightStore.getState().reconcileCount();
          return true;
        })
        .catch(() => {
          useInsightStore.getState().reconcileCount();
          toast.error("Failed to save insight. Please try again.");
          return false;
        });
    },
    []
  );

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto px-3 sm:px-4 py-4 sm:py-6"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        {messages.map((msg, idx) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              isLastAssistant={idx === lastAssistantIdx}
              onRetry={readOnly ? undefined : handleRetry}
              onResend={readOnly || msg.role !== "user" ? undefined : onRetry}
              onFeedback={readOnly ? undefined : handleFeedback}
              onMarkInsight={readOnly ? undefined : handleMarkInsight}
              readOnly={readOnly ?? false}
            />
        ))}

      </div>
    </div>
  );
});
