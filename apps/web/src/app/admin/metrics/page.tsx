"use client";

// Query Metrics admin tab — virtualized, cursor-paginated view over
// /api/v1/admin/metrics with a filter bar. Rows expand to show the full SQL
// and the agent trace summary.

import { useMemo, useState } from "react";

import { VirtualizedTable, type VirtualizedColumn } from "@/components/admin/virtualized-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAdminMetrics, type MetricsFilters, type MetricsRow } from "@/hooks/use-admin-metrics";

const ALL = "__all__";

function toTs(dateStr: string): number | undefined {
  if (!dateStr) return undefined;
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return undefined;
  return Math.floor(d.getTime() / 1000);
}

function formatTs(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export default function MetricsPage() {
  const [userFilter, setUserFilter] = useState("");
  const [dbFilter, setDbFilter] = useState("");
  const [thumbsFilter, setThumbsFilter] = useState<string>(ALL);
  const [agentMode, setAgentMode] = useState<string>(ALL);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [applied, setApplied] = useState<MetricsFilters>({});

  const query = useAdminMetrics(applied);
  const rows = useMemo(
    () => query.data?.pages.flatMap((p) => p.rows) ?? [],
    [query.data],
  );

  function apply() {
    setApplied({
      user: userFilter.trim() || undefined,
      db: dbFilter.trim() || undefined,
      thumbs:
        thumbsFilter === "up" || thumbsFilter === "down"
          ? (thumbsFilter as "up" | "down")
          : undefined,
      agent_mode: agentMode === ALL ? undefined : agentMode,
      from: toTs(fromDate),
      to: toTs(toDate),
    });
  }

  function reset() {
    setUserFilter("");
    setDbFilter("");
    setThumbsFilter(ALL);
    setAgentMode(ALL);
    setFromDate("");
    setToDate("");
    setApplied({});
  }

  const columns: VirtualizedColumn<MetricsRow>[] = [
    {
      key: "time",
      header: "Time",
      width: "170px",
      render: (r) => (
        <span className="text-xs text-muted-foreground">{formatTs(r.created_at)}</span>
      ),
    },
    {
      key: "user",
      header: "User",
      width: "1.2fr",
      render: (r) => (
        <span className="truncate">{r.user_email ?? r.user_id ?? "—"}</span>
      ),
    },
    {
      key: "db",
      header: "DB",
      width: "0.9fr",
      render: (r) => <span className="truncate">{r.db_id ?? "—"}</span>,
    },
    {
      key: "mode",
      header: "Mode",
      width: "100px",
      render: (r) => <span>{r.agent_mode ?? "—"}</span>,
    },
    {
      key: "tokens",
      header: "Tokens",
      width: "120px",
      render: (r) => (
        <span className="text-xs text-muted-foreground">
          {(r.tokens_in ?? 0) + (r.tokens_out ?? 0)}
          <span className="ml-1 opacity-60">
            ({r.tokens_in ?? 0}/{r.tokens_out ?? 0})
          </span>
        </span>
      ),
    },
    {
      key: "thumbs",
      header: "Thumbs",
      width: "80px",
      render: (r) =>
        r.thumbs === "up" ? (
          <span className="text-green-600 dark:text-green-400">up</span>
        ) : r.thumbs === "down" ? (
          <span className="text-red-600 dark:text-red-400">down</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Query metrics</h2>
        <p className="text-sm text-muted-foreground">
          Every chat turn, with SQL, mode, tokens, and feedback.
        </p>
      </div>

      <div className="grid gap-3 rounded-lg border border-border bg-card p-3 md:grid-cols-6">
        <div className="space-y-1">
          <Label className="text-xs">User ID</Label>
          <Input value={userFilter} onChange={(e) => setUserFilter(e.target.value)} placeholder="uuid" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Database</Label>
          <Input value={dbFilter} onChange={(e) => setDbFilter(e.target.value)} placeholder="db_id" />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Thumbs</Label>
          <Select value={thumbsFilter} onValueChange={setThumbsFilter}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Any</SelectItem>
              <SelectItem value="up">Up</SelectItem>
              <SelectItem value="down">Down</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Agent mode</Label>
          <Select value={agentMode} onValueChange={setAgentMode}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Any</SelectItem>
              <SelectItem value="sql">sql</SelectItem>
              <SelectItem value="agent">agent</SelectItem>
              <SelectItem value="rag">rag</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">From</Label>
          <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">To</Label>
          <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
        </div>
        <div className="md:col-span-6 flex items-center gap-2">
          <Button onClick={apply} size="sm">Apply</Button>
          <Button onClick={reset} size="sm" variant="outline">Reset</Button>
          <span className="ml-auto text-xs text-muted-foreground">
            {rows.length} loaded{query.hasNextPage ? " · more available" : ""}
          </span>
        </div>
      </div>

      {query.error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          Failed to load metrics.
        </div>
      ) : (
        <VirtualizedTable<MetricsRow>
          rows={rows}
          columns={columns}
          rowKey={(r) => r.id}
          isFetchingMore={query.isFetchingNextPage}
          onEndReached={() => {
            if (query.hasNextPage && !query.isFetchingNextPage) {
              void query.fetchNextPage();
            }
          }}
          renderExpanded={(r) => (
            <div className="space-y-3 text-xs">
              {r.question && (
                <div>
                  <p className="font-medium text-muted-foreground">Question</p>
                  <p className="whitespace-pre-wrap">{r.question}</p>
                </div>
              )}
              {r.sql && (
                <div>
                  <p className="font-medium text-muted-foreground">SQL</p>
                  <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-[11px] leading-snug">
                    {r.sql}
                  </pre>
                </div>
              )}
              {r.agent_trace_summary && (
                <div>
                  <p className="font-medium text-muted-foreground">Agent trace</p>
                  <pre className="whitespace-pre-wrap rounded bg-muted p-2 font-mono text-[11px] leading-snug">
                    {r.agent_trace_summary}
                  </pre>
                </div>
              )}
            </div>
          )}
        />
      )}
    </div>
  );
}
