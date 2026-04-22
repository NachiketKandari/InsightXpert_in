"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Database } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchProfile } from "@/lib/databases/api";
import type { DatabaseListItem, DatabaseProfile } from "@/types/database";

interface DatabaseCardProps {
  item: DatabaseListItem;
}

export function DatabaseCard({ item }: DatabaseCardProps) {
  const [profile, setProfile] = useState<DatabaseProfile | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const p = await fetchProfile(item.db_id);
      if (!cancelled) {
        setProfile(p);
        setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.db_id]);

  const totalColumns = profile?.tables.reduce(
    (sum, t) => sum + t.columns.length,
    0,
  );

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 hover:border-primary/60 transition-colors">
      <div className="flex items-center gap-2">
        <Database className="size-4 text-muted-foreground" />
        <h3 className="flex-1 truncate font-mono text-sm font-medium">
          {item.db_id}
        </h3>
        <Badge variant="outline" className="text-[10px] uppercase">
          {item.source}
        </Badge>
      </div>

      <div className="text-xs text-muted-foreground min-h-[1.5rem]">
        {!loaded ? (
          <span className="opacity-50">Loading…</span>
        ) : profile ? (
          <span className="text-emerald-600 dark:text-emerald-400">
            Profiled · {profile.tables.length} table
            {profile.tables.length !== 1 ? "s" : ""}
            {totalColumns != null ? ` · ${totalColumns} columns` : ""}
          </span>
        ) : (
          <span>Not profiled</span>
        )}
      </div>

      <div className="mt-auto flex justify-end">
        <Button asChild size="sm" variant="secondary">
          <Link href={`/databases/${encodeURIComponent(item.db_id)}`}>
            Open
            <ArrowRight className="size-3.5 ml-1" />
          </Link>
        </Button>
      </div>
    </div>
  );
}
