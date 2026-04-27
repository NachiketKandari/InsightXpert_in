"use client";

import { useState, useEffect, useCallback } from "react";
import { ChevronDown, Database, Check, Loader2, Plus, FileUp, Plug } from "lucide-react";
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
import { apiCall } from "@/lib/api";
import { useChatStore } from "@/stores/chat-store";
import type { DatabaseListItem } from "@/types/database";

/**
 * DatasetSelector — header affordance for picking the active database.
 *
 * Backend contract: `GET /api/v1/databases` returns
 * `[{db_id, source}, ...]`. The selected `db_id` is persisted in the chat
 * store (`selectedDbId`) and threaded into chat + sql/execute requests.
 *
 * This selector replaced a fork-era "datasets" implementation that was
 * hitting the non-existent `/api/v1/datasets/public` endpoint, which
 * silently returned null and left the UI showing "No dataset" forever.
 */
export function DatasetSelector() {
  const [databases, setDatabases] = useState<DatabaseListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [csvUploadOpen, setCsvUploadOpen] = useState(false);
  const [sqliteUploadOpen, setSqliteUploadOpen] = useState(false);
  const [connectDbOpen, setConnectDbOpen] = useState(false);

  const selectedDbId = useChatStore((s) => s.selectedDbId);
  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);

  const fetchDatabases = useCallback(async () => {
    const data = await apiCall<DatabaseListItem[]>("/api/v1/databases");
    if (data) {
      setDatabases(data);
      // Auto-select first DB if nothing is selected or the previously
      // selected one is no longer visible. Pull `selectedDbId` fresh via
      // `getState()` to avoid threading it through this callback's deps
      // (which would re-run the subscription on every change).
      const current = useChatStore.getState().selectedDbId;
      const stillVisible = data.some((d) => d.db_id === current);
      if (!stillVisible && data.length > 0) {
        setSelectedDbId(data[0].db_id);
      }
    }
    setLoading(false);
  }, [setSelectedDbId]);

  useEffect(() => {
    // External sync — kick a fetch + subscribe to cross-component invalidations.
    // The lint rule below flags any setState-in-effect; the set* calls here
    // happen after an `await` in fetchDatabases (i.e. post-async-boundary),
    // which is exactly the external-sync pattern the rule's docs endorse.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchDatabases();
    const handler = () => void fetchDatabases();
    window.addEventListener("databases-changed", handler);
    return () => window.removeEventListener("databases-changed", handler);
  }, [fetchDatabases]);

  const activeDb = databases.find((d) => d.db_id === selectedDbId);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 h-8 px-2.5 text-xs font-medium text-muted-foreground hover:text-foreground"
            disabled={loading}
            aria-label="Select database"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Database className="size-3.5 text-primary dark:text-cyan-accent" />
            )}
            <span className="hidden sm:inline max-w-[160px] truncate">
              {loading
                ? "Loading..."
                : (activeDb?.db_id ?? (databases.length === 0 ? "No databases" : "Select database"))}
            </span>
            <ChevronDown className="size-3 opacity-60" />
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Databases
          </DropdownMenuLabel>
          {databases.length === 0 && !loading && (
            <DropdownMenuItem disabled>No databases found</DropdownMenuItem>
          )}
          {databases.map((db) => (
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
          <DropdownMenuItem
            onClick={() => setCsvUploadOpen(true)}
            className="gap-2 cursor-pointer text-primary dark:text-cyan-accent"
          >
            <Plus className="size-3.5" />
            <span className="text-sm font-medium">Upload CSV</span>
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
