"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import type {
  DatabaseProfile,
  SchemaResponse,
  TableProfile,
} from "@/types/database";

interface SchemaPanelProps {
  schema: SchemaResponse | null;
  profile: DatabaseProfile | null;
}

export function SchemaPanel({ schema, profile }: SchemaPanelProps) {
  const tables = schema?.tables ?? [];
  const profileByTable = new Map<string, TableProfile>(
    (profile?.tables ?? []).map((t) => [t.name, t]),
  );

  return (
    <div className="rounded-md border border-border bg-card">
      <Tabs defaultValue="tables" className="w-full">
        <div className="border-b border-border px-3 pt-3">
          <TabsList>
            <TabsTrigger value="tables">Tables</TabsTrigger>
            <TabsTrigger value="ddl">DDL</TabsTrigger>
            {profile && <TabsTrigger value="profiles">Column profiles</TabsTrigger>}
          </TabsList>
        </div>

        <TabsContent value="tables" className="p-3">
          {tables.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tables.</p>
          ) : (
            <ul className="divide-y divide-border">
              {tables.map((name) => {
                const tp = profileByTable.get(name);
                return (
                  <li key={name} className="py-2 flex items-center justify-between">
                    <span className="font-mono text-sm">{name}</span>
                    {tp && (
                      <span className="text-xs text-muted-foreground">
                        {tp.columns.length} col{tp.columns.length !== 1 ? "s" : ""}
                        {tp.row_count != null && ` · ${tp.row_count.toLocaleString()} rows`}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="ddl" className="p-3">
          <pre className="max-h-[480px] overflow-auto rounded-md bg-muted p-3 text-xs font-mono whitespace-pre">
            {schema?.ddl ?? "(no schema)"}
          </pre>
        </TabsContent>

        {profile && (
          <TabsContent value="profiles" className="p-3 space-y-2">
            {profile.tables.map((t) => (
              <TableProfileBlock key={t.name} table={t} />
            ))}
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

function TableProfileBlock({ table }: { table: TableProfile }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60">
        {open ? (
          <ChevronDown className="size-4" />
        ) : (
          <ChevronRight className="size-4" />
        )}
        <span className="font-mono text-sm">{table.name}</span>
        <span className="ml-auto text-xs text-muted-foreground">
          {table.columns.length} col{table.columns.length !== 1 ? "s" : ""}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-1 space-y-1 pl-6">
          {table.columns.map((c) => (
            <li
              key={c.name}
              className="rounded border border-border bg-background px-2 py-1.5"
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs">{c.name}</span>
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  {c.type}
                </span>
              </div>
              {c.short_summary && (
                <p className="text-xs text-muted-foreground mt-1">{c.short_summary}</p>
              )}
              <dl className="mt-1 grid grid-cols-3 gap-x-2 text-[10px] text-muted-foreground">
                <div>
                  <dt className="inline">count </dt>
                  <dd className="inline font-mono">{c.stats.count}</dd>
                </div>
                <div>
                  <dt className="inline">nulls </dt>
                  <dd className="inline font-mono">{c.stats.null_count}</dd>
                </div>
                <div>
                  <dt className="inline">distinct </dt>
                  <dd className="inline font-mono">{c.stats.distinct_count}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
