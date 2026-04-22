"use client";

import { useEffect, useState } from "react";
import { Database, Check, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import { apiCall } from "@/lib/api";
import { useChatStore } from "@/stores/chat-store";
import type { DatabaseListItem } from "@/types/database";

/**
 * DatabasePickerPanel — first-class DB picker shown on the landing screen
 * (no active conversation yet). Renders every DB the user can see as a
 * clickable card so they don't have to discover the header dropdown.
 *
 * Selecting a card writes to `useChatStore().selectedDbId`, which is what
 * chat + sql-execute requests now thread through.
 */
export function DatabasePickerPanel() {
  const [databases, setDatabases] = useState<DatabaseListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const selectedDbId = useChatStore((s) => s.selectedDbId);
  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await apiCall<DatabaseListItem[]>("/api/v1/databases");
      if (cancelled) return;
      setDatabases(data ?? []);
      setLoading(false);
      if (data && data.length > 0 && !selectedDbId) {
        setSelectedDbId(data[0].db_id);
      }
    })();
    const handler = () => {
      apiCall<DatabaseListItem[]>("/api/v1/databases").then((d) => {
        if (!cancelled && d) setDatabases(d);
      });
    };
    window.addEventListener("databases-changed", handler);
    return () => {
      cancelled = true;
      window.removeEventListener("databases-changed", handler);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <div className="mt-6 flex items-center justify-center text-muted-foreground/70 text-xs gap-2">
        <Loader2 className="size-3.5 animate-spin" />
        Loading databases…
      </div>
    );
  }

  if (databases.length === 0) {
    return (
      <div className="mt-6 text-center text-xs text-muted-foreground/70">
        No databases available. Upload a CSV or SQLite file from the header menu.
      </div>
    );
  }

  return (
    <div className="mt-6 w-full max-w-2xl">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wider text-muted-foreground/70">
          Databases
        </span>
        <span className="text-[11px] text-muted-foreground/60">
          {selectedDbId ? (
            <>Active: <span className="font-mono text-foreground/80">{selectedDbId}</span></>
          ) : (
            "Pick one to start"
          )}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
        {databases.map((db) => {
          const active = db.db_id === selectedDbId;
          return (
            <motion.button
              key={db.db_id}
              type="button"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setSelectedDbId(db.db_id)}
              className={`glass group relative flex items-center gap-2 rounded-xl px-3 py-2 text-left transition-shadow hover:shadow-[0_0_20px_rgba(6,182,212,0.15)] ${
                active ? "ring-1 ring-primary/50 dark:ring-cyan-accent/50" : ""
              }`}
              aria-pressed={active}
            >
              <Database
                className={`size-4 shrink-0 ${
                  active
                    ? "text-primary dark:text-cyan-accent"
                    : "text-muted-foreground"
                }`}
              />
              <div className="flex-1 min-w-0">
                <div className="font-mono text-xs truncate">{db.db_id}</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                  {db.source}
                </div>
              </div>
              {active && (
                <Check className="size-3.5 text-primary dark:text-cyan-accent shrink-0" />
              )}
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
