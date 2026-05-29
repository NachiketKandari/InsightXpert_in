"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ListChecks, Share2 } from "lucide-react";
import { useSSEChat } from "@/hooks/use-sse-chat";
import { useChatStore } from "@/stores/chat-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useDatabases } from "@/hooks/use-databases";
import { WelcomeScreen } from "@/components/chat/welcome-screen";
import { MessageList } from "@/components/chat/message-list";
import { MessageInput } from "@/components/chat/message-input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ShareDialog } from "@/components/chat/share-dialog";

export function ChatPanel() {
  const { sendMessage, stopStreaming, isStreaming } = useSSEChat();
  const agentMode = useSettingsStore((s) => s.agentMode);
  const conversation = useChatStore((s) => s.activeConversation());
  const isLoadingConversation = useChatStore((s) => s.isLoadingConversation);
  const selectedDbId = useChatStore((s) => s.selectedDbId);
  const hasMessages = conversation && conversation.messages.length > 0;
  // While a conversation's messages are being fetched, render the chat shell
  // (header + input + message-list region) immediately instead of a full-pane
  // spinner. This makes the conversation switch feel instant — the user sees
  // the new layout right away, with a subtle inline spinner inside the
  // message region until the data arrives. Avoids the >1s "blank pane"
  // perception when the BE round-trip dominates.
  const isFetchingExisting =
    isLoadingConversation && !!conversation && conversation.messages.length === 0;

  const [shareOpen, setShareOpen] = useState(false);
  const { data: databases = [] } = useDatabases();

  const setSampleQuestionsOpen = useChatStore((s) => s.setSampleQuestionsOpen);
  const conversationId = conversation?.id ?? null;

  const currentDb = databases.find((d) => d.db_id === selectedDbId);
  const isUnprofiled = selectedDbId && currentDb && !currentDb.has_profile;

  const dbKindHint: "bundled" | "uploaded" | "postgres" | "libsql" | "none" | "unknown" =
    !selectedDbId
      ? "none"
      : !currentDb
      ? "unknown"
      : currentDb.source === "uploaded"
      ? "uploaded"
      : currentDb.source === "postgres"
      ? "postgres"
      : currentDb.source === "libsql"
      ? "libsql"
      : "bundled";

  const handleSend = useCallback(
    (message: string) => {
      sendMessage(message, agentMode);
    },
    [sendMessage, agentMode],
  );

  const unprofiledNotice = isUnprofiled ? (
    <div className="flex items-center gap-2 px-3 py-2 mx-3 mb-1 rounded-md border border-orange-500/30 bg-orange-500/5">
      <AlertTriangle className="size-3.5 text-orange-500 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-muted-foreground">
          <Badge
            variant="outline"
            className="mr-1.5 text-[10px] leading-none border-orange-500/50 text-orange-600 dark:text-orange-400"
          >
            Not Profiled
          </Badge>
          This database needs to be profiled before you can query it.
        </p>
      </div>
      <Button asChild size="sm" variant="outline" className="h-7 text-xs">
        <Link href={`/databases/${encodeURIComponent(selectedDbId)}`}>
          Run Profile
        </Link>
      </Button>
    </div>
  ) : null;

  return (
    <div className="flex h-full flex-col">
      {isFetchingExisting ? (
        <>
          <div className="flex items-center justify-end px-2 pt-1">
            <div className="size-9" />
          </div>
          <div className="flex flex-1 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-foreground" />
          </div>
          <MessageInput
            onSend={handleSend}
            onStop={stopStreaming}
            isStreaming={isStreaming}
          />
        </>
      ) : hasMessages ? (
        <>
          <div className="flex items-center justify-end gap-1 px-2 pt-1">
            {selectedDbId && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSampleQuestionsOpen(true)}
                aria-label="View sample questions"
              >
                <ListChecks className="h-4 w-4" />
              </Button>
            )}
            {conversationId ? (
              <>
                <Button
                  data-testid="share-open-btn"
                  variant="ghost"
                  size="icon"
                  onClick={() => setShareOpen(true)}
                  aria-label="Share this chat"
                  disabled={isStreaming}
                >
                  <Share2 className="h-4 w-4" />
                </Button>
                <ShareDialog
                  conversationId={conversationId}
                  dbKindHint={dbKindHint}
                  open={shareOpen}
                  onOpenChange={setShareOpen}
                />
              </>
            ) : null}
          </div>
          <MessageList onRetry={handleSend} />
          {isUnprofiled ? (
            unprofiledNotice
          ) : (
            <MessageInput
              onSend={handleSend}
              onStop={stopStreaming}
              isStreaming={isStreaming}
            />
          )}
        </>
      ) : (
        <WelcomeScreen
          onSendMessage={handleSend}
          onStop={stopStreaming}
          isStreaming={isStreaming}
        />
      )}
    </div>
  );
}
