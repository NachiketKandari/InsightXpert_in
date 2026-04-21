"use client";

import React, { useState } from "react";
import {
  ChevronRight,
  GitBranch,
  Link2,
  ListChecks,
  Network,
  Quote,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type {
  CandidateSQLsGeneratedData,
  ColumnSource,
  JoinPathsAddedData,
  LinkedSchemaFinalData,
  LiteralsExtractedData,
  SchemaLinkingStartedData,
  SemanticMatchesData,
} from "@/types/chunks";

/**
 * Schema-linking transparency renderers.
 *
 * The backend emits the linking stages as independent chunks in spec order.
 * We ship one tiny panel per chunk type (so they stack as a natural timeline
 * under the status strip), plus one bigger `LinkedSchemaFinalChunk` that
 * renders the terminal summary with per-column source badges — the product
 * differentiator.
 */

// -------------------------------------------------------------------------
// Shared primitives
// -------------------------------------------------------------------------

function LinkingCard({
  icon,
  title,
  children,
  defaultOpen = false,
  accent = "sky",
}: {
  icon: React.ReactNode;
  title: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  accent?: "sky" | "violet" | "amber" | "emerald";
}) {
  const [open, setOpen] = useState(defaultOpen);
  const accentClass = {
    sky: "text-sky-500",
    violet: "text-violet-500",
    amber: "text-amber-500",
    emerald: "text-emerald-500",
  }[accent];

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
            <span className={cn("shrink-0", accentClass)}>{icon}</span>
            <span className="text-xs font-medium text-foreground">{title}</span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 pt-2 border-t border-border/50">
            {children}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

// -------------------------------------------------------------------------
// Individual chunk renderers
// -------------------------------------------------------------------------

export function SchemaLinkingStartedChunk({
  data,
}: {
  data: SchemaLinkingStartedData;
}) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
      <Link2 className="size-3.5 shrink-0 text-sky-500" />
      <span>
        Linking schema for{" "}
        <span className="font-mono text-foreground">{data.db_id}</span>
      </span>
    </div>
  );
}

export function CandidateSqlsChunk({
  data,
}: {
  data: CandidateSQLsGeneratedData;
}) {
  const candidates = data.candidates ?? [];
  if (candidates.length === 0) return null;
  return (
    <LinkingCard
      icon={<Sparkles className="size-3.5" />}
      title={
        <>
          Trial SQLs
          <Badge variant="secondary" className="ml-2 text-[10px] font-normal">
            {candidates.length}
          </Badge>
        </>
      }
      accent="amber"
    >
      <ol className="space-y-1.5 list-decimal list-inside">
        {candidates.map((sql, i) => (
          <li
            key={i}
            className="text-[11px] font-mono text-muted-foreground leading-relaxed break-all"
          >
            {sql}
          </li>
        ))}
      </ol>
    </LinkingCard>
  );
}

export function LiteralsExtractedChunk({
  data,
}: {
  data: LiteralsExtractedData;
}) {
  const literals = data.literals ?? [];
  const matches = data.matches ?? {};
  if (literals.length === 0) return null;
  return (
    <LinkingCard
      icon={<Quote className="size-3.5" />}
      title={
        <>
          Literals extracted
          <Badge variant="secondary" className="ml-2 text-[10px] font-normal">
            {literals.length}
          </Badge>
        </>
      }
      accent="amber"
    >
      <ul className="space-y-1.5">
        {literals.map((lit) => {
          const cols = matches[lit] ?? [];
          return (
            <li key={lit} className="text-xs">
              <span className="font-mono text-foreground">&quot;{lit}&quot;</span>
              {cols.length > 0 && (
                <span className="text-muted-foreground">
                  {" "}→{" "}
                  {cols.map((c, i) => (
                    <React.Fragment key={c}>
                      {i > 0 && ", "}
                      <span className="font-mono text-foreground/80">{c}</span>
                    </React.Fragment>
                  ))}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </LinkingCard>
  );
}

export function SemanticMatchesChunk({
  data,
}: {
  data: SemanticMatchesData;
}) {
  const matches = data.matches ?? [];
  if (matches.length === 0) return null;
  return (
    <LinkingCard
      icon={<ListChecks className="size-3.5" />}
      title={
        <>
          Semantic matches
          <Badge variant="secondary" className="ml-2 text-[10px] font-normal">
            {matches.length}
          </Badge>
        </>
      }
      accent="violet"
    >
      <ul className="space-y-1">
        {matches.map((m, i) => (
          <li
            key={`${m.column}-${i}`}
            className="flex items-center justify-between text-xs"
          >
            <span className="font-mono text-foreground">{m.column}</span>
            <span className="text-muted-foreground tabular-nums font-mono text-[11px]">
              {m.score.toFixed(3)}
            </span>
          </li>
        ))}
      </ul>
    </LinkingCard>
  );
}

export function JoinPathsAddedChunk({
  data,
}: {
  data: JoinPathsAddedData;
}) {
  const edges = data.edges ?? [];
  if (edges.length === 0) return null;
  return (
    <LinkingCard
      icon={<GitBranch className="size-3.5" />}
      title={
        <>
          Join paths
          <Badge variant="secondary" className="ml-2 text-[10px] font-normal">
            {edges.length}
          </Badge>
        </>
      }
      accent="sky"
    >
      <ul className="space-y-1">
        {edges.map((e, i) => (
          <li key={i} className="text-xs text-foreground flex items-center gap-2">
            <span className="font-mono">{e.from}</span>
            <span className="text-muted-foreground">→</span>
            <span className="font-mono">{e.to}</span>
            <Badge variant="outline" className="text-[10px] font-normal ml-auto">
              {e.kind}
            </Badge>
          </li>
        ))}
      </ul>
    </LinkingCard>
  );
}

// -------------------------------------------------------------------------
// Linked-schema-final — the product differentiator
// -------------------------------------------------------------------------

const SOURCE_STYLES: Record<string, { label: string; className: string }> = {
  trial_sql: {
    label: "trial",
    className:
      "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30",
  },
  semantic: {
    label: "semantic",
    className:
      "bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/30",
  },
  lsh: {
    label: "lsh",
    className:
      "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400 border-fuchsia-500/30",
  },
  join_path: {
    label: "join",
    className:
      "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/30",
  },
};

function SourceBadge({ source }: { source: ColumnSource | string }) {
  const style = SOURCE_STYLES[source] ?? {
    label: source,
    className: "bg-muted text-muted-foreground border-border",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-1 py-[1px] text-[9px] font-medium uppercase tracking-wide",
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}

export function LinkedSchemaFinalChunk({
  data,
}: {
  data: LinkedSchemaFinalData;
}) {
  const [open, setOpen] = useState(true);
  const columnSources = data.column_sources ?? {};
  const linkedColumns = data.linked_columns ?? [];
  const linkedTables = data.linked_tables ?? [];

  // Columns displayed: prefer `linked_columns` order, fall back to keys of
  // `column_sources`.
  const display =
    linkedColumns.length > 0
      ? linkedColumns
      : Object.keys(columnSources);

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
            <Network className="size-3.5 shrink-0 text-emerald-500" />
            <span className="text-xs font-medium text-foreground">
              Linked schema
            </span>
            <Badge variant="secondary" className="text-[10px] font-normal">
              {linkedTables.length} table{linkedTables.length === 1 ? "" : "s"}
            </Badge>
            <Badge variant="secondary" className="text-[10px] font-normal">
              {display.length} column{display.length === 1 ? "" : "s"}
            </Badge>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 pt-2 border-t border-border/50 space-y-3">
            {data.question_interpretation && (
              <div className="text-xs">
                <div className="text-muted-foreground mb-0.5">
                  Question interpretation
                </div>
                <div className="text-foreground/90 italic">
                  {data.question_interpretation}
                </div>
              </div>
            )}

            {linkedTables.length > 0 && (
              <div className="text-xs">
                <div className="text-muted-foreground mb-1">Tables</div>
                <div className="flex flex-wrap gap-1">
                  {linkedTables.map((t) => (
                    <span
                      key={t}
                      className="inline-flex items-center rounded-md border border-border bg-muted/40 px-2 py-0.5 font-mono text-[11px]"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {display.length > 0 && (
              <div className="text-xs">
                <div className="text-muted-foreground mb-1">
                  Columns (colored by source)
                </div>
                <ul className="space-y-1">
                  {display.map((col) => {
                    const sources = (columnSources[col] ?? []) as string[];
                    return (
                      <li
                        key={col}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="font-mono text-[11px] text-foreground truncate">
                          {col}
                        </span>
                        <div className="flex items-center gap-1 flex-wrap justify-end">
                          {sources.length > 0 ? (
                            sources.map((s, i) => (
                              <SourceBadge key={`${s}-${i}`} source={s} />
                            ))
                          ) : (
                            <span className="text-[10px] text-muted-foreground/60">
                              —
                            </span>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>

                {/* Legend */}
                <div className="mt-3 flex items-center gap-2 flex-wrap text-[10px] text-muted-foreground">
                  <span>Sources:</span>
                  {(["trial_sql", "semantic", "lsh", "join_path"] as const).map(
                    (s) => (
                      <SourceBadge key={s} source={s} />
                    ),
                  )}
                </div>
              </div>
            )}

            {data.schema_text && (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">
                  Raw schema DDL
                </summary>
                <pre className="mt-2 p-2 bg-muted/40 rounded-md overflow-x-auto font-mono text-[10px] leading-relaxed">
                  {data.schema_text}
                </pre>
              </details>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
