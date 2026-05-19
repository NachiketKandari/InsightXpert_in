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
 * The chunk is emitted by the server-side classifier in `routes/chat.py`
 * when the client sends `agent_mode="auto"`. No client-side preflight is
 * needed — the server races classification against profile prefetch so it
 * adds no extra wall-clock time.
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
