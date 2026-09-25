"use client";

import { useEffect, useMemo, useRef } from "react";
import { useShallow } from "zustand/shallow";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useChatStore } from "@/stores/chat-store";
import { ConversationItem } from "./conversation-item";
import type { Conversation } from "@/types/chat";

interface ConversationGroup {
  label: string;
  conversations: Conversation[];
}

function groupConversationsByDate(conversations: Conversation[]): ConversationGroup[] {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();

  const groups: Record<string, Conversation[]> = {
    Today: [],
    Older: [],
  };

  // Sort by updatedAt descending first
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);

  for (const conv of sorted) {
    if (conv.updatedAt >= startOfToday) {
      groups["Today"].push(conv);
    } else {
      groups["Older"].push(conv);
    }
  }

  // Return only non-empty groups in order
  const orderedLabels = ["Today", "Older"];
  return orderedLabels
    .filter((label) => groups[label].length > 0)
    .map((label) => ({ label, conversations: groups[label] }));
}

type Row =
  | { type: "header"; key: string; label: string }
  | { type: "item"; key: string; conversation: Conversation };

export function ConversationList() {
  const conversations = useChatStore(useShallow((s) => s.conversations));
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const isLoadingConversations = useChatStore((s) => s.isLoadingConversations);

  const groups = useMemo(() => groupConversationsByDate(conversations), [conversations]);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (const group of groups) {
      out.push({ type: "header", key: `header-${group.label}`, label: group.label });
      for (const conv of group.conversations) {
        out.push({ type: "item", key: conv.id, conversation: conv });
      }
    }
    return out;
  }, [groups]);

  const parentRef = useRef<HTMLDivElement | null>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => (rows[index]?.type === "header" ? 28 : 52),
    overscan: 8,
  });

  // Keep the active conversation visible when it changes (e.g. after New Chat).
  useEffect(() => {
    if (!activeConversationId) return;
    const index = rows.findIndex(
      (r) => r.type === "item" && r.conversation.id === activeConversationId
    );
    if (index >= 0) {
      virtualizer.scrollToIndex(index, { align: "auto" });
    }
    // Only re-run when the active id changes, not on every scroll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversationId]);

  if (isLoadingConversations) {
    return (
      <div className="flex flex-col gap-0.5 p-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="px-3 py-3">
            <div
              className="h-4 animate-pulse rounded bg-muted/60"
              style={{ width: `${60 + Math.sin(i * 1.7) * 30}%` }}
            />
          </div>
        ))}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-muted-foreground">
        No conversations yet
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      role="list"
      aria-label="Conversations"
      className="flex-1 min-h-0 overflow-y-auto"
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          position: "relative",
          width: "100%",
        }}
      >
        {virtualizer.getVirtualItems().map((v) => {
          const row = rows[v.index];
          if (!row) return null;
          return (
            <div
              key={row.key}
              role="listitem"
              data-index={v.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${v.start}px)`,
              }}
            >
              {row.type === "header" ? (
                <p className="px-4 pt-2 pb-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  {row.label}
                </p>
              ) : (
                <div className="px-2">
                  <ConversationItem
                    conversation={row.conversation}
                    isActive={row.conversation.id === activeConversationId}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
