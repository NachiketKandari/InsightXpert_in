"use client";

import { useCallback, useState } from "react";
import { ListChecks, Share2 } from "lucide-react";
import { useSSEChat } from "@/hooks/use-sse-chat";
import { useChatStore } from "@/stores/chat-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useDatabases } from "@/hooks/use-databases";
import { WelcomeScreen } from "@/components/chat/welcome-screen";
import { MessageList } from "@/components/chat/message-list";
import { MessageInput } from "@/components/chat/message-input";
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
  const dbKindHint: "bundled" | "uploaded" | "postgres" | "none" | "unknown" =
    !selectedDbId
      ? "none"
      : !currentDb
      ? "unknown"
      : currentDb.source === "uploaded"
      ? "uploaded"
      : "bundled";

  const handleSend = useCallback(
    (message: string) => {
      sendMessage(message, agentMode);
    },
    [sendMessage, agentMode],
  );

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
          <MessageInput
            onSend={handleSend}
            onStop={stopStreaming}
            isStreaming={isStreaming}
          />
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
