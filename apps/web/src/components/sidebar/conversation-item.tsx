"use client";

import React, { useState, useRef, useEffect } from "react";
import { MoreHorizontal, Pencil, Trash2, MessageSquare, Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useChatStore } from "@/stores/chat-store";
import { useIsMobile } from "@/hooks/use-media-query";
import type { Conversation } from "@/types/chat";
import { cn, relativeTime, formatDate } from "@/lib/utils";

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
}

export const ConversationItem = React.memo(function ConversationItem({
  conversation,
  isActive,
}: ConversationItemProps) {
  const setActiveConversation = useChatStore((s) => s.setActiveConversation);
  const setLeftSidebar = useChatStore((s) => s.setLeftSidebar);
  const isMobile = useIsMobile();
  const deleteConversation = useChatStore((s) => s.deleteConversation);
  const renameConversation = useChatStore((s) => s.renameConversation);

  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isRenaming && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isRenaming]);

  const handleConfirmRename = () => {
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== conversation.title) {
      renameConversation(conversation.id, trimmed);
    }
    setIsRenaming(false);
  };

  const handleCancelRename = () => {
    setRenameValue(conversation.title);
    setIsRenaming(false);
  };

  const handleRenameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleConfirmRename();
    } else if (e.key === "Escape") {
      handleCancelRename();
    }
  };

  if (isRenaming) {
    return (
      <div className="flex items-center gap-1.5 w-full rounded-md px-2 py-1.5 bg-accent">
        <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
        <Input
          ref={inputRef}
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onKeyDown={handleRenameKeyDown}
          onBlur={handleConfirmRename}
          className="h-6 text-sm px-1.5 py-0 border-primary/50"
        />
        <button
          type="button"
          className="inline-flex items-center justify-center size-5 rounded-md shrink-0 hover:bg-accent-foreground/10 focus-visible:outline-2 focus-visible:outline-primary"
          onClick={handleConfirmRename}
          title="Confirm"
          aria-label="Confirm rename"
        >
          <Check className="size-3 text-emerald-500" />
        </button>
        <button
          type="button"
          className="inline-flex items-center justify-center size-5 rounded-md shrink-0 hover:bg-accent-foreground/10 focus-visible:outline-2 focus-visible:outline-primary"
          onClick={handleCancelRename}
          title="Cancel"
          aria-label="Cancel rename"
        >
          <X className="size-3 text-muted-foreground" />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group flex items-center gap-2 w-full rounded-md px-2.5 py-2 text-left transition-colors",
        "hover:bg-accent/50 focus-within:bg-accent/50",
        isActive && "bg-accent/60 border-l-2 border-cyan-accent"
      )}
    >
      <button
        type="button"
        onClick={() => {
          setActiveConversation(conversation.id);
          // Mobile sidebar is an overlay sheet — dismiss it on selection.
          if (isMobile) setLeftSidebar(false);
        }}
        aria-label={`Open conversation: ${conversation.title}`}
        aria-current={isActive ? "true" : undefined}
        className="flex flex-1 min-w-0 items-center gap-2 rounded-md text-left cursor-pointer focus-visible:outline-2 focus-visible:outline-primary"
      >
      <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <p className="text-sm truncate flex-1 min-w-0" title={conversation.title}>
            {conversation.title}
          </p>
          <span className="text-xs text-muted-foreground shrink-0">
            {conversation.updatedAt > 86400000 ? (() => {
              const startOfToday = new Date();
              startOfToday.setHours(0, 0, 0, 0);
              return conversation.updatedAt >= startOfToday.getTime()
                ? relativeTime(conversation.updatedAt)
                : formatDate(conversation.updatedAt);
            })() : null}
          </span>
        </div>
      </div>
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Conversation actions for ${conversation.title}`}
            title="Conversation actions"
            className={cn(
              "inline-flex items-center justify-center size-7 rounded-md shrink-0",
              "text-muted-foreground hover:text-foreground hover:bg-accent-foreground/10",
              "opacity-100 lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100 focus-visible:opacity-100 transition-all focus-visible:outline-2 focus-visible:outline-primary"
            )}
          >
            <MoreHorizontal className="size-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          <DropdownMenuItem
            onClick={(e) => {
              e.stopPropagation();
              setRenameValue(conversation.title);
              setIsRenaming(true);
            }}
          >
            <Pencil className="size-4" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            onClick={(e) => {
              e.stopPropagation();
              deleteConversation(conversation.id);
            }}
          >
            <Trash2 className="size-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
});
