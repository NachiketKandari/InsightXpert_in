"use client";

// Audit Log admin tab — virtualized, cursor-paginated view over
// /api/v1/admin/audit with a filter bar. Matches the Metrics tab's shape.

import { useMemo, useState } from "react";

import {
  VirtualizedTable,
  type VirtualizedColumn,
} from "@/components/admin/virtualized-table";
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
import { useAdminAudit, type AuditFilters, type AuditRow } from "@/hooks/use-admin-audit";

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

export default function AuditPage() {
  const [userFilter, setUserFilter] = useState("");
  const [actionFilter, setActionFilter] = useState<string>(ALL);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [applied, setApplied] = useState<AuditFilters>({});

  const query = useAdminAudit(applied);
  const rows = useMemo(
    () => query.data?.pages.flatMap((p) => p.rows) ?? [],
    [query.data],
  );

  function apply() {
    setApplied({
      user: userFilter.trim() || undefined,
      action: actionFilter === ALL ? undefined : actionFilter,
      from: toTs(fromDate),
      to: toTs(toDate),
    });
  }

  function reset() {
    setUserFilter("");
    setActionFilter(ALL);
    setFromDate("");
    setToDate("");
    setApplied({});
  }

  const columns: VirtualizedColumn<AuditRow>[] = [
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
      width: "1fr",
      render: (r) => <span className="truncate">{r.user_id ?? "—"}</span>,
    },
    {
      key: "method",
      header: "Method",
      width: "90px",
      render: (r) => <span className="font-mono text-xs">{r.method ?? "—"}</span>,
    },
    {
      key: "path",
      header: "Path",
      width: "2fr",
      render: (r) => <span className="truncate font-mono text-xs">{r.path ?? "—"}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "80px",
      render: (r) => {
        const s = r.status_code ?? 0;
        const cls =
          s >= 500
            ? "text-red-600 dark:text-red-400"
            : s >= 400
              ? "text-yellow-700 dark:text-yellow-400"
              : "text-muted-foreground";
        return <span className={cls}>{s || "—"}</span>;
      },
    },
    {
      key: "ip",
      header: "IP",
      width: "130px",
      render: (r) => <span className="text-xs text-muted-foreground">{r.ip ?? "—"}</span>,
    },
  ];

  return (
    <div className="flex flex-col" style={{ minHeight: "calc(100vh - 9rem)" }}>
      <div className="shrink-0 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Audit log</h2>
          <p className="text-sm text-muted-foreground">
            Every admin / mutating request, reverse-chronological.
          </p>
        </div>

        <div className="grid gap-3 rounded-lg border border-border bg-card p-3 md:grid-cols-5">
          <div className="space-y-1 md:col-span-2">
            <Label className="text-xs">User ID</Label>
            <Input value={userFilter} onChange={(e) => setUserFilter(e.target.value)} placeholder="uuid" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Method</Label>
            <Select value={actionFilter} onValueChange={setActionFilter}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Any</SelectItem>
                <SelectItem value="GET">GET</SelectItem>
                <SelectItem value="POST">POST</SelectItem>
                <SelectItem value="PATCH">PATCH</SelectItem>
                <SelectItem value="PUT">PUT</SelectItem>
                <SelectItem value="DELETE">DELETE</SelectItem>
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
          <div className="md:col-span-5 flex items-center gap-2">
            <Button onClick={apply} size="sm">Apply</Button>
            <Button onClick={reset} size="sm" variant="outline">Reset</Button>
            <span className="ml-auto text-xs text-muted-foreground">
              {rows.length} loaded{query.hasNextPage ? " · more available" : ""}
            </span>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 mt-4">
        {query.error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            Failed to load audit log.
          </div>
        ) : (
          <VirtualizedTable<AuditRow>
            rows={rows}
            columns={columns}
            rowKey={(r) => r.id}
            isFetchingMore={query.isFetchingNextPage}
            height="fill"
            onEndReached={() => {
              if (query.hasNextPage && !query.isFetchingNextPage) {
                void query.fetchNextPage();
              }
            }}
          />
        )}
      </div>
    </div>
  );
}
