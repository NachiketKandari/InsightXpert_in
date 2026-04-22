"use client";

// Databases admin tab: shows every DB (owner, visibility, shared_with) via
// the enriched GET /api/v1/admin/databases/ endpoint and lets an admin change
// visibility. The server is the source of truth — we invalidate + refetch on
// mutation rather than optimistically stubbing "private".

import { useMemo, useState } from "react";
import { toast } from "sonner";

import { VisibilityMenu, VisibilityBadge } from "@/components/admin/visibility-menu";
import { Input } from "@/components/ui/input";
import {
  useAdminDatabases,
  useSetDbVisibility,
  useSetDbPipelineMode,
  type PipelineModeDefault,
  type Visibility,
} from "@/hooks/use-admin-databases";

export default function DatabasesPage() {
  const { data, isLoading, error } = useAdminDatabases();
  const setVis = useSetDbVisibility();
  const setMode = useSetDbPipelineMode();
  const [filter, setFilter] = useState("");

  const rows = useMemo(() => {
    const all = data ?? [];
    if (!filter.trim()) return all;
    const q = filter.toLowerCase();
    return all.filter(
      (d) =>
        d.db_id.toLowerCase().includes(q) ||
        (d.owner_email?.toLowerCase().includes(q) ?? false),
    );
  }, [data, filter]);

  async function handleChange(
    db_id: string,
    next: Visibility,
    sharedWith?: string[],
  ) {
    try {
      await setVis.mutateAsync({ db_id, visibility: next, shared_with: sharedWith });
      toast.success(`${db_id} is now ${next}.`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      if (detail === "invalid_visibility") {
        toast.error("Invalid visibility option.");
      } else {
        toast.error(`Failed to update ${db_id}.`);
      }
    }
  }

  async function handleModeChange(db_id: string, raw: string) {
    // "" (empty option value) is our sentinel for "inherit default".
    const next: PipelineModeDefault =
      raw === "linked" || raw === "full_schema" ? raw : null;
    try {
      await setMode.mutateAsync({ db_id, pipeline_mode_default: next });
      toast.success(
        next === null
          ? `${db_id}: pipeline mode cleared (uses default).`
          : `${db_id}: pipeline mode set to ${next}.`,
      );
    } catch {
      toast.error(`Failed to update pipeline mode for ${db_id}.`);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Databases</h2>
          <p className="text-sm text-muted-foreground">
            All SQLite databases known to this instance. Set visibility to
            control who can query each one.
          </p>
        </div>
        <div className="w-64">
          <Input
            placeholder="Filter by db_id or owner email"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <div className="grid grid-cols-[1.5fr_1.2fr_0.8fr_0.8fr_0.9fr_auto] gap-3 border-b border-border px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <div>Database</div>
          <div>Owner</div>
          <div>Visibility</div>
          <div>Shared</div>
          <div>Pipeline mode</div>
          <div className="text-right">Actions</div>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary" />
          </div>
        )}
        {error && (
          <div className="px-4 py-6 text-sm text-destructive">
            Failed to load databases.
          </div>
        )}
        {!isLoading && rows.length === 0 && !error && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            No databases match.
          </div>
        )}

        {rows.map((d) => {
          const sharedIds = d.shared_with.map((s) => s.user_id);
          const sharedLabel =
            d.visibility === "shared" && d.shared_with.length > 0
              ? `${d.shared_with.length} user${d.shared_with.length === 1 ? "" : "s"}`
              : "—";
          return (
            <div
              key={d.db_id}
              className="grid grid-cols-[1.5fr_1.2fr_0.8fr_0.8fr_0.9fr_auto] items-center gap-3 border-b border-border/50 px-4 py-2 text-sm last:border-b-0"
            >
              <div className="font-mono text-xs">{d.db_id}</div>
              <div className="text-xs text-muted-foreground truncate">
                {d.owner_email ?? <span className="italic">bundled</span>}
              </div>
              <div>
                <VisibilityBadge value={d.visibility} />
              </div>
              <div
                className="text-xs text-muted-foreground"
                title={
                  d.shared_with.length > 0
                    ? d.shared_with.map((s) => s.email).join(", ")
                    : undefined
                }
              >
                {sharedLabel}
              </div>
              <div>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs"
                  value={d.pipeline_mode_default ?? ""}
                  onChange={(e) => handleModeChange(d.db_id, e.target.value)}
                  aria-label={`Pipeline mode for ${d.db_id}`}
                >
                  <option value="">Default (linked)</option>
                  <option value="linked">Linked</option>
                  <option value="full_schema">Full schema</option>
                </select>
              </div>
              <div className="flex justify-end">
                <VisibilityMenu
                  value={d.visibility}
                  sharedWith={sharedIds}
                  onSubmit={(next, sw) => handleChange(d.db_id, next, sw)}
                  label={`Visibility — ${d.db_id}`}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
