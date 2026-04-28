"use client";

import { MessageBubble } from "@/components/chat/message-bubble";
import type { SharedSnapshotPublic } from "@/lib/share-api";
import type { Message } from "@/types/chat";

export function SharedMessageList({
  snapshot,
}: {
  snapshot: SharedSnapshotPublic;
}) {
  // Convert the snapshot's compact message shape into the Message type that
  // MessageBubble expects. Chunks are empty — content-only rendering.
  const messages: Message[] = snapshot.messages.map((m, i) => ({
    id: `shared-${i}`,
    role: m.role,
    content: m.content,
    chunks: [],
    timestamp: m.created_at,
    feedback: null,
    feedbackComment: null,
    inputTokens: null,
    outputTokens: null,
    generationTimeMs: null,
    wallTimeMs: null,
  }));

  return (
    <div className="flex flex-col gap-6">
      {messages.map((msg, idx) => (
        <MessageBubble
          key={msg.id}
          message={msg}
          isLastAssistant={
            msg.role === "assistant" &&
            messages.slice(idx + 1).every((m) => m.role !== "assistant")
          }
          readOnly
        />
      ))}
    </div>
  );
}
