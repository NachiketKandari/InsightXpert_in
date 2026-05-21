"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Light as SyntaxHighlighter } from "react-syntax-highlighter";
import sql from "react-syntax-highlighter/dist/esm/languages/hljs/sql";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { CopyButton } from "@/components/ui/copy-button";
import { cn } from "@/lib/utils";
import { useSyntaxTheme } from "@/hooks/use-syntax-theme";
import type { SqlGeneratedData } from "@/types/chunks";

SyntaxHighlighter.registerLanguage("sql", sql);

interface SqlGeneratedChunkProps {
  data: SqlGeneratedData;
}

/**
 * Tier-3: `sql_generated`. Replaces the legacy bare `sql` chunk. Shows the
 * generated SQL with an iteration badge so refinement loops are visible.
 */
export function SqlGeneratedChunk({ data }: SqlGeneratedChunkProps) {
  const [open, setOpen] = useState(true);
  const syntaxTheme = useSyntaxTheme();
  const iteration = data.iteration ?? 0;
  const isRefinement = iteration > 0;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border border-border bg-card/50 overflow-hidden">
        <div className="flex items-center">
          <CollapsibleTrigger asChild>
            <button className="flex items-center gap-2 flex-1 pl-3 py-2 hover:bg-accent/30 transition-colors text-left">
              <ChevronRight
                className={cn(
                  "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                  open && "rotate-90",
                )}
              />
              <Badge variant="secondary" className="text-xs">
                {isRefinement ? "SQL Refined" : "SQL Generated"}
              </Badge>
              <Badge
                variant="outline"
                className={cn(
                  "text-[10px] font-normal",
                  isRefinement && "border-amber-500/30 text-amber-600 dark:text-amber-400",
                )}
              >
                iteration {iteration}
              </Badge>
            </button>
          </CollapsibleTrigger>
          <CopyButton text={data.sql} iconClassName="size-3.5" className="mr-2" />
        </div>
        <CollapsibleContent>
          <div className="px-3 pb-3 border-t border-border/50">
            <SyntaxHighlighter
              language="sql"
              style={syntaxTheme}
              customStyle={{
                background: "transparent",
                padding: "0.75rem 0",
                margin: 0,
                fontSize: "0.8rem",
                fontFamily: "var(--font-mono)",
              }}
              wrapLongLines
            >
              {data.sql}
            </SyntaxHighlighter>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
