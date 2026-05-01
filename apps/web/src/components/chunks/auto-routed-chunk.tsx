"use client";

import { Sparkles, Zap } from "lucide-react";

interface AutoRoutedData {
  mode: "basic" | "agentic";
  reason: string;
}

/**
 * Compact pill rendered at the top of an assistant message when the chat
 * was sent in `auto` mode. Shows the routed mode + the classifier's reason.
 *
 * The chunk is emitted either by the FE pre-flight call to
 * `POST /api/v1/chat/route` (injected synthetically into the message) or by
 * the server-side fallback in `routes/chat.py` (when a client sent
 * `agent_mode="auto"` directly).
 */
export function AutoRoutedChunk({ data }: { data: AutoRoutedData }) {
  const isAgentic = data.mode === "agentic";
  const ModeIcon = isAgentic ? Zap : Sparkles;
  const modeLabel = isAgentic ? "agentic" : "basic";
  const modeColor = isAgentic ? "text-emerald-500" : "text-amber-500";

  return (
    <div
      className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-0.5 text-xs"
      role="status"
      aria-label={`Auto-routed to ${modeLabel} mode`}
    >
      <Sparkles className="size-3 text-violet-500" aria-hidden />
      <span className="text-violet-600 dark:text-violet-300 font-medium">
        Auto
      </span>
      <span className="text-muted-foreground">→</span>
      <ModeIcon className={`size-3 ${modeColor}`} aria-hidden />
      <span className={`${modeColor} font-medium`}>{modeLabel}</span>
      {data.reason ? (
        <>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground truncate max-w-[40ch]">
            {data.reason}
          </span>
        </>
      ) : null}
    </div>
  );
}
