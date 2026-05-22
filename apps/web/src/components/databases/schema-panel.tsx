"use client";

import { useCallback, useState } from "react";
import { ChevronDown, ChevronRight, Pencil } from "lucide-react";

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
import { Button } from "@/components/ui/button";
import { updateColumnProfile } from "@/lib/databases/api";
import type {
  ColumnProfile,
  DatabaseProfile,
  SchemaResponse,
  TableProfile,
} from "@/types/database";

interface SchemaPanelProps {
  schema: SchemaResponse | null;
  profile: DatabaseProfile | null;
  dbId: string;
  onProfileRefresh: () => void;
}

export function SchemaPanel({
  schema,
  profile,
  dbId,
  onProfileRefresh,
}: SchemaPanelProps) {
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
            {profile && (
              <TabsTrigger value="profiles">Column profiles</TabsTrigger>
            )}
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
                  <li
                    key={name}
                    className="py-2 flex items-center justify-between"
                  >
                    <span className="font-mono text-sm">{name}</span>
                    {tp && (
                      <span className="text-xs text-muted-foreground">
                        {tp.columns.length} col
                        {tp.columns.length !== 1 ? "s" : ""}
                        {tp.row_count != null &&
                          ` · ${tp.row_count.toLocaleString()} rows`}
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
          <TabsContent
            value="profiles"
            className="p-3 space-y-2 max-h-[65vh] overflow-y-auto"
          >
            {profile.tables.map((t) => (
              <TableProfileBlock
                key={t.name}
                table={t}
                dbId={dbId}
                onProfileRefresh={onProfileRefresh}
              />
            ))}
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

function TableProfileBlock({
  table,
  dbId,
  onProfileRefresh,
}: {
  table: TableProfile;
  dbId: string;
  onProfileRefresh: () => void;
}) {
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
            <ColumnCard
              key={c.name}
              column={c}
              tableName={table.name}
              dbId={dbId}
              onProfileRefresh={onProfileRefresh}
            />
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ColumnCard({
  column: c,
  tableName,
  dbId,
  onProfileRefresh,
}: {
  column: ColumnProfile;
  tableName: string;
  dbId: string;
  onProfileRefresh: () => void;
}) {
  return (
    <li className="rounded border border-border bg-background px-2 py-1.5">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs">{c.name}</span>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {c.type}
        </span>
      </div>

      {c.short_summary && (
        <EditableField
          label={null}
          value={c.short_summary}
          fieldPath="short_summary"
          dbId={dbId}
          tableName={tableName}
          columnName={c.name}
          onProfileRefresh={onProfileRefresh}
        />
      )}

      {c.long_summary && (
        <EditableField
          label={null}
          value={c.long_summary}
          fieldPath="long_summary"
          dbId={dbId}
          tableName={tableName}
          columnName={c.name}
          onProfileRefresh={onProfileRefresh}
        />
      )}

      {c.quirks.semantic_hint && (
        <EditableField
          label="Hint"
          value={c.quirks.semantic_hint}
          fieldPath="quirks.semantic_hint"
          dbId={dbId}
          tableName={tableName}
          columnName={c.name}
          onProfileRefresh={onProfileRefresh}
        />
      )}

      {c.quirks.aliases && c.quirks.aliases.length > 0 && (
        <EditableField
          label="Aliases"
          value={c.quirks.aliases}
          fieldPath="quirks.aliases"
          dbId={dbId}
          tableName={tableName}
          columnName={c.name}
          onProfileRefresh={onProfileRefresh}
        />
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
  );
}

function EditableField({
  label,
  value,
  fieldPath,
  dbId,
  tableName,
  columnName,
  onProfileRefresh,
}: {
  label: string | null;
  value: unknown;
  fieldPath: string;
  dbId: string;
  tableName: string;
  columnName: string;
  onProfileRefresh: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);

  const displayText = Array.isArray(value) ? value.join(", ") : String(value);

  const startEdit = useCallback(() => {
    setEditValue(
      Array.isArray(value)
        ? value.join(", ")
        : typeof value === "string"
          ? value
          : "",
    );
    setEditing(true);
  }, [value]);

  const cancelEdit = useCallback(() => setEditing(false), []);

  const saveEdit = useCallback(async () => {
    setSaving(true);
    let v: unknown = editValue;
    if (fieldPath === "quirks.aliases" || fieldPath === "aliases") {
      v = editValue
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }
    const ok = await updateColumnProfile(
      dbId,
      tableName,
      columnName,
      fieldPath,
      v,
    );
    setSaving(false);
    if (ok) {
      setEditing(false);
      onProfileRefresh();
    }
  }, [editValue, fieldPath, dbId, tableName, columnName, onProfileRefresh]);

  if (editing) {
    return (
      <div className="mt-1 space-y-1">
        <textarea
          className="w-full rounded border border-border bg-background px-2 py-1 text-xs font-mono resize-y min-h-[40px]"
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          rows={2}
          autoFocus
        />
        <div className="flex items-center gap-1">
          <Button
            variant="default"
            size="sm"
            className="h-6 px-2 text-[10px]"
            onClick={saveEdit}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[10px]"
            onClick={cancelEdit}
            disabled={saving}
          >
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="mt-0.5 group flex items-start gap-1 cursor-pointer hover:bg-accent/30 rounded px-1 -mx-1 py-0.5"
      onClick={startEdit}
      title="Click to edit"
    >
      <span className="text-xs text-muted-foreground flex-1">
        {label && (
          <span className="font-medium text-[10px] uppercase tracking-wide mr-1">
            {label}:
          </span>
        )}
        {displayText}
      </span>
      <Pencil className="size-3 shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground" />
    </div>
  );
}
