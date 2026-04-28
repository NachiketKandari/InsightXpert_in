"use client";

import Link from "next/link";
import { ArrowRight, Database } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DatabaseListItem } from "@/types/database";

interface DatabaseCardProps {
  item: DatabaseListItem;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function DatabaseCard({ item }: DatabaseCardProps) {
  const tables = item.table_count ?? 0;
  const columns = item.column_count ?? 0;
  const rows = item.row_count ?? 0;

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
        {item.has_profile ? (
          <span className="text-emerald-600 dark:text-emerald-400">
            Profiled · {tables} table{tables !== 1 ? "s" : ""} · {columns}{" "}
            column{columns !== 1 ? "s" : ""}
            {rows > 0 ? ` · ${formatCount(rows)} rows` : ""}
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
