"use client";

import { Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ProfileLoadedData } from "@/types/chunks";

interface ProfileLoadedChunkProps {
  data: ProfileLoadedData;
}

/**
 * Tier-3: `profile_loaded`. Small badge-style banner shown once per turn to
 * confirm that the database schema profile has been loaded (and whether it
 * came from cache).
 */
export function ProfileLoadedChunk({ data }: ProfileLoadedChunkProps) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
      <Database className="size-3.5 shrink-0 text-emerald-500" />
      <span>
        Loaded profile for <span className="font-mono text-foreground">{data.db_id}</span>
      </span>
      <Badge variant="secondary" className="text-[10px] font-normal">
        {data.table_count} table{data.table_count === 1 ? "" : "s"}
      </Badge>
      <Badge variant="secondary" className="text-[10px] font-normal">
        {data.column_count} column{data.column_count === 1 ? "" : "s"}
      </Badge>
      {data.from_cache && (
        <Badge variant="outline" className="text-[10px] font-normal border-emerald-500/30 text-emerald-600 dark:text-emerald-400">
          cached
        </Badge>
      )}
    </div>
  );
}
