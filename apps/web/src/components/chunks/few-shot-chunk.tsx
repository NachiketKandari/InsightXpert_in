"use client";

import React, { useState } from "react";
import { ChevronRight, BookOpen } from "lucide-react";
import { Light as SyntaxHighlighter } from "react-syntax-highlighter";
import sql from "react-syntax-highlighter/dist/esm/languages/hljs/sql";
import { Badge } from "@/components/ui/badge";
import { useSyntaxTheme } from "@/hooks/use-syntax-theme";

SyntaxHighlighter.registerLanguage("sql", sql);
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { FewShotRetrievedData } from "@/types/chunks";

/**
 * Renders the ``few_shot_retrieved`` SSE chunk emitted by the route's
 * preflight (concurrent with the profile prefetch). Mirrors the visual
 * weight of ``schema-linking-chunk.tsx`` LinkingCard pattern — small
 * collapsible card with a header that summarises which BIRD-train pair we
 * pulled and an expanded body that shows the gold SQL.
 */
export function FewShotRetrievedChunk({
  data,
}: {
  data: FewShotRetrievedData;
}) {
  const [open, setOpen] = useState(false);
  const syntaxTheme = useSyntaxTheme();
  const sim = typeof data.similarity === "number" ? data.similarity : 0;
  const simPct = Math.round(sim * 100);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border border-border bg-card/50 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-2 w-full px-3 py-2 hover:bg-accent/30 transition-colors text-left">
            <ChevronRight
              className={cn(
                "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                open && "rotate-90",
              )}
            />
            <span className="shrink-0 text-violet-500">
              <BookOpen className="size-3.5" />
            </span>
            <span className="text-xs font-medium text-foreground flex-1 truncate">
              Pulled similar example from{" "}
              <span className="font-mono text-foreground">
                {data.source_db_id}
              </span>
            </span>
            <Badge
              variant="outline"
              className="text-[10px] tabular-nums shrink-0"
            >
              {simPct}% match
            </Badge>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 pt-2 border-t border-border/50 space-y-2">
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">
                Question
              </div>
              <div className="text-xs text-foreground">{data.question}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">
                Gold SQL
              </div>
              <SyntaxHighlighter
                language="sql"
                style={syntaxTheme}
                customStyle={{
                  fontSize: "11px",
                  padding: "8px",
                  margin: 0,
                  borderRadius: "4px",
                }}
                wrapLongLines
              >
                {data.gold_sql}
              </SyntaxHighlighter>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
