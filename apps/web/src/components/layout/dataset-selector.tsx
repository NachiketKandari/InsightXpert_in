"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Database, Check, Loader2, Plus, FileUp, Plug, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CsvUploadDialog } from "@/components/dataset/csv-upload-dialog";
import { SqliteUploadDialog } from "@/components/dataset/sqlite-upload-dialog";
import { ConnectDbDialog } from "@/components/dataset/connect-db-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useDatabases } from "@/hooks/use-databases";
import {
  useSampleQuestionStatus,
  useGenerateSampleQuestions,
  postRegenerate,
} from "@/hooks/use-sample-questions";
import { useChatStore } from "@/stores/chat-store";

/**
 * DatasetSelector — header affordance for picking the active database.
 *
 * The trigger label renders synchronously from `selectedDbId` (chat-store) so
 * it never blinks "Loading…" on remount. The dropdown's list is fetched via
 * `useDatabases()` (TanStack Query, 30s staleTime); the spinner only appears
 * inside the open menu while the first cold fetch is in flight. Cross-component
 * invalidations come through `queryClient.invalidateQueries(['databases','list'])`
 * — the legacy `databases-changed` window event has been retired.
 */
export function DatasetSelector() {
  const [csvUploadOpen, setCsvUploadOpen] = useState(false);
  const [sqliteUploadOpen, setSqliteUploadOpen] = useState(false);
  const [connectDbOpen, setConnectDbOpen] = useState(false);

  const selectedDbId = useChatStore((s) => s.selectedDbId);
  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);

  const { data: databases, isLoading } = useDatabases();
  const queryClient = useQueryClient();

  // Lightweight status poll (GET /sample-questions/status) — avoids fetching
  // the full profile JSON just to check generation state.
  const { data: sqStatus } = useSampleQuestionStatus(selectedDbId ?? undefined);

  const ensureSampleQuestions = useGenerateSampleQuestions(selectedDbId ?? undefined);

  const regenerateSampleQuestions = useMutation({
    mutationFn: () => postRegenerate(selectedDbId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sample-questions-status", selectedDbId] });
      queryClient.invalidateQueries({ queryKey: ["profile", selectedDbId] });
    },
  });

  // Auto-select the first DB when nothing is selected (or the previous
  // selection has disappeared). Driven by query state, not a fetch effect.
  useEffect(() => {
    if (!databases || databases.length === 0) return;
    const stillVisible = databases.some((d) => d.db_id === selectedDbId);
    if (!stillVisible) {
      setSelectedDbId(databases[0].db_id);
    }
  }, [databases, selectedDbId, setSelectedDbId]);

  // Auto-retry when the user selects a DB whose previous sample-question
  // generation failed. Uses the lightweight status endpoint to avoid pulling
  // the full profile JSON just for the status check.
  const ensureTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!selectedDbId || !sqStatus) return;
    if (sqStatus.status === "failed") {
      if (ensureTimerRef.current) clearTimeout(ensureTimerRef.current);
      ensureTimerRef.current = setTimeout(() => {
        ensureSampleQuestions.mutate();
      }, 300);
    }
    return () => {
      if (ensureTimerRef.current) {
        clearTimeout(ensureTimerRef.current);
        ensureTimerRef.current = null;
      }
    };
  }, [selectedDbId, sqStatus, ensureSampleQuestions]);

  // Trigger label: render whatever the user already chose — no fetch
  // dependency. Falls back to a sensible static string only when there is
  // genuinely no selection yet (first ever load on a brand-new account).
  const triggerLabel = selectedDbId ?? "Select database";

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 h-8 px-2.5 text-xs font-medium text-muted-foreground hover:text-foreground"
            aria-label="Select database"
          >
            <Database className="size-3.5 text-primary dark:text-cyan-accent" />
            <span className="hidden sm:inline max-w-[160px] truncate">
              {triggerLabel}
            </span>
            <ChevronDown className="size-3 opacity-60" />
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Databases
          </DropdownMenuLabel>

          {(() => {
            const list = databases ?? [];
            if (isLoading && list.length === 0) {
              return (
                <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" />
                  Loading…
                </div>
              );
            }
            if (!isLoading && list.length === 0) {
              return <DropdownMenuItem disabled>No databases found</DropdownMenuItem>;
            }
            return null;
          })()}

          {databases?.map((db) => (
            <DropdownMenuItem
              key={db.db_id}
              onClick={() => setSelectedDbId(db.db_id)}
              className="flex items-center gap-2 cursor-pointer"
            >
              {db.db_id === selectedDbId ? (
                <Check className="size-3.5 shrink-0 text-primary dark:text-cyan-accent" />
              ) : (
                <span className="size-3.5 shrink-0" />
              )}
              <span className="flex-1 truncate text-sm font-mono">{db.db_id}</span>
              <span className="text-[10px] uppercase text-muted-foreground/70 shrink-0">
                {db.source}
              </span>
            </DropdownMenuItem>
          ))}

          <DropdownMenuSeparator />
          {selectedDbId && (
            <DropdownMenuItem
              onClick={() => regenerateSampleQuestions.mutate()}
              disabled={regenerateSampleQuestions.isPending}
              className="gap-2 cursor-pointer"
            >
              <RefreshCw className={`size-3.5 ${regenerateSampleQuestions.isPending ? "animate-spin" : ""}`} />
              <span className="text-sm font-medium">Regenerate sample questions</span>
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => setCsvUploadOpen(true)}
            className="gap-2 cursor-pointer text-primary dark:text-cyan-accent"
          >
            <Plus className="size-3.5" />
            <span className="text-sm font-medium">Upload CSV / Excel</span>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => setSqliteUploadOpen(true)}
            className="gap-2 cursor-pointer text-primary dark:text-cyan-accent"
          >
            <FileUp className="size-3.5" />
            <span className="text-sm font-medium">Upload SQLite</span>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => setConnectDbOpen(true)}
            className="gap-2 cursor-pointer text-primary dark:text-cyan-accent"
          >
            <Plug className="size-3.5" />
            <span className="text-sm font-medium">Connect a database</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <CsvUploadDialog
        open={csvUploadOpen}
        onOpenChange={setCsvUploadOpen}
        onUploadSuccess={() => {}}
      />
      <SqliteUploadDialog
        open={sqliteUploadOpen}
        onOpenChange={setSqliteUploadOpen}
      />
      <ConnectDbDialog
        open={connectDbOpen}
        onOpenChange={setConnectDbOpen}
      />
    </>
  );
}
