"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { Search, Copy, Check, MessageSquareText, RefreshCw, Sparkles, AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSampleQuestions } from "@/hooks/use-sample-questions";
import type { SampleQuestionCategory } from "@/types/sample-questions";

interface SampleQuestionsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dbId?: string;
}

function SkeletonRows() {
  return (
    <div className="space-y-5">
      {[1, 2, 3].map((cat) => (
        <section key={cat}>
          <div className="h-3 w-32 bg-muted/60 rounded animate-pulse mb-2" />
          <div className="space-y-1.5">
            {[1, 2, 3].map((q) => (
              <div key={q} className="h-8 rounded-lg bg-muted/40 animate-pulse" />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function SampleQuestionsModal({ open, onOpenChange, dbId }: SampleQuestionsModalProps) {
  const [search, setSearch] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<string | null>(null);
  const autoFiredRef = useRef(false);

  const { data, profileQuery, regenerate } = useSampleQuestions(dbId);

  // Auto-fire regenerate once when modal opens and there's no data yet
  useEffect(() => {
    if (open && dbId && !data && !profileQuery.isLoading && !profileQuery.isError && !autoFiredRef.current) {
      autoFiredRef.current = true;
      regenerate.mutate();
    }
    if (!open) {
      autoFiredRef.current = false;
    }
  }, [open, dbId, data, profileQuery.isLoading, profileQuery.isError, regenerate]);

  const status = data?.status;
  const isPending = !data || status === "pending";
  const isFailed = status === "failed";
  const isRegenPending = regenerate.isPending;

  const categories: SampleQuestionCategory[] = data?.categories ?? [];

  const filtered = useMemo(() => {
    const term = search.toLowerCase().trim();
    if (!term) return categories;
    return categories
      .map((cat) => ({
        ...cat,
        questions: cat.questions.filter((q) => q.toLowerCase().includes(term)),
      }))
      .filter((cat) => cat.questions.length > 0);
  }, [search, categories]);

  const totalVisible = useMemo(
    () => filtered.reduce((sum, cat) => sum + cat.questions.length, 0),
    [filtered],
  );

  const handleSelect = useCallback(
    (question: string) => {
      // Import dynamically to avoid circular: useChatStore is available globally
      // We use a custom event to keep the modal decoupled from the store import
      window.dispatchEvent(new CustomEvent("sample-question-selected", { detail: question }));
      onOpenChange(false);
      setSearch("");
    },
    [onOpenChange],
  );

  // Listen for the custom event and pipe into chat store
  useEffect(() => {
    const handler = (e: Event) => {
      const question = (e as CustomEvent<string>).detail;
      // Dynamically access the store without importing at module level
      // (avoids the circular dep the old code had)
      import("@/stores/chat-store").then(({ useChatStore }) => {
        useChatStore.getState().setPendingInput(question);
      });
    };
    window.addEventListener("sample-question-selected", handler);
    return () => window.removeEventListener("sample-question-selected", handler);
  }, []);

  const handleCopy = useCallback(
    (question: string, key: string, e: React.MouseEvent) => {
      e.stopPropagation();
      navigator.clipboard.writeText(question);
      setCopiedIndex(key);
      setTimeout(() => setCopiedIndex(null), 1500);
    },
    [],
  );

  const headerTitle = isPending
    ? "Generating starter questions…"
    : "Sample Questions";

  const statusBadge = (() => {
    if (!data) return null;
    if (status === "ok") {
      return (
        <Badge variant="secondary" className="text-[10px] font-medium gap-1">
          <Sparkles className="size-2.5" />
          Tailored to {dbId}
          {data.model ? ` (${data.model})` : ""}
        </Badge>
      );
    }
    if (status === "fallback") {
      return (
        <Badge variant="outline" className="text-[10px] font-medium">
          Auto-generated from schema
        </Badge>
      );
    }
    return null;
  })();

  return (
    <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) setSearch(""); }}>
      <DialogContent
        className="w-[95vw] max-w-4xl h-[85vh] flex flex-col p-0 bg-card border-border/60 shadow-2xl"
        showCloseButton
      >
        {/* Header */}
        <div className="px-5 pt-4 pb-3 border-b border-border/50 shrink-0 space-y-3">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center justify-center size-7 rounded-md bg-primary/10 dark:bg-cyan-accent/10">
              <MessageSquareText className="size-3.5 text-primary dark:text-cyan-accent" />
            </div>
            <DialogTitle className="text-sm font-semibold tracking-wide">
              {headerTitle}
            </DialogTitle>
            {!isPending && !isFailed && (
              <Badge variant="secondary" className="text-[10px] font-medium">
                {totalVisible} questions
              </Badge>
            )}
            {statusBadge}
            <div className="ml-auto">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs gap-1 text-muted-foreground hover:text-foreground"
                onClick={() => regenerate.mutate()}
                disabled={isPending || isRegenPending}
                title="Regenerate sample questions"
              >
                <RefreshCw className={`size-3 ${isRegenPending ? "animate-spin" : ""}`} />
                Regenerate
              </Button>
            </div>
          </div>

          {!isPending && !isFailed && (
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search questions..."
                className="pl-8 h-8 text-sm"
              />
            </div>
          )}
        </div>

        {/* Scrollable body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-3">
          {isPending ? (
            <SkeletonRows />
          ) : isFailed ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-sm text-muted-foreground">
              <AlertTriangle className="size-6 text-destructive/60" />
              <p>Failed to generate questions.</p>
              {data?.error && (
                <p className="text-xs text-muted-foreground/70">{data.error}</p>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => regenerate.mutate()}
                disabled={isRegenPending}
                className="gap-1"
              >
                <RefreshCw className={`size-3 ${isRegenPending ? "animate-spin" : ""}`} />
                Try again
              </Button>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
              No questions match your search.
            </div>
          ) : (
            <div className="space-y-5">
              {filtered.map((cat) => (
                <section key={cat.name}>
                  <div className="sticky top-0 z-10 bg-card/95 backdrop-blur-sm pb-1.5 pt-0.5">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-primary/70 dark:text-cyan-accent/80 flex items-center gap-2">
                      {cat.name}
                      <span className="text-[10px] font-normal text-muted-foreground">
                        ({cat.questions.length})
                      </span>
                    </h3>
                  </div>
                  <div className="space-y-0.5">
                    {cat.questions.map((q, i) => {
                      const key = `${cat.name}-${i}`;
                      return (
                        <div
                          key={key}
                          onClick={() => handleSelect(q)}
                          className="group flex items-center gap-2 rounded-lg px-3 py-2 cursor-pointer hover:bg-accent/50 dark:hover:bg-accent/60 transition-colors"
                        >
                          <span className="flex-1 text-sm text-foreground/85 leading-relaxed">
                            {q}
                          </span>
                          <button
                            onClick={(e) => handleCopy(q, key, e)}
                            className="shrink-0 size-7 flex items-center justify-center rounded-md opacity-0 group-hover:opacity-100 hover:bg-accent transition-all cursor-pointer"
                            title="Copy to clipboard"
                          >
                            {copiedIndex === key ? (
                              <Check className="size-3.5 text-green-500" />
                            ) : (
                              <Copy className="size-3.5 text-muted-foreground" />
                            )}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
