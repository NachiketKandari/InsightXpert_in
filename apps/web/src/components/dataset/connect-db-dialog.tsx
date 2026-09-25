"use client";

import { useCallback, useState } from "react";
import { CheckCircle2, Loader2, Plug, AlertCircle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  createConnection,
  testConnection,
  type ConnectionKind,
  type LibsqlConfig,
  type MySQLConfig,
  type OracleConfig,
  type PostgresConfig,
} from "@/lib/connections/api";
import {
  clearVisible,
  filterTables,
  formatRowCount,
  isUnsupported,
  selectableTables,
  selectAllVisible,
  toggleSelection,
  type TableDetailsMap,
} from "@/lib/connections/tables";
import { useChatStore } from "@/stores/chat-store";
import { useQueryClient } from "@tanstack/react-query";

/**
 * ConnectDbDialog — Phase 4b "bring your own database" entry point.
 *
 * Two-step UX (per backend contract): user fills the form → clicks
 * "Test connection" → on success the discovered tables are shown and Save
 * unlocks. Without a successful test the row is never persisted, so we
 * never store credentials that don't actually work.
 *
 * Backend routes:
 *   POST /api/v1/connections/test → { ok, tables[] } or 400 {detail}
 *   POST /api/v1/connections      → 201 {db_id}
 */
interface ConnectDbDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnectSuccess?: (dbId: string) => void;
}

const DB_ID_PATTERN = /^[a-z0-9][a-z0-9_\-]{0,62}$/;

const DEFAULT_POSTGRES: PostgresConfig = {
  host: "",
  port: 5432,
  database: "",
  username: "",
  password: "",
  ssl_mode: "require",
  schema: "public",
};

const DEFAULT_MYSQL: MySQLConfig = {
  host: "",
  port: 3306,
  database: "",
  username: "",
  password: "",
  ssl_enabled: true,
  charset: "utf8mb4",
};

const DEFAULT_LIBSQL: LibsqlConfig = { url: "", auth_token: "" };

const DEFAULT_ORACLE: OracleConfig = {
  host: "",
  port: 1521,
  service_name: "",
  schema: "",
  username: "",
  password: "",
};

export function ConnectDbDialog({
  open,
  onOpenChange,
  onConnectSuccess,
}: ConnectDbDialogProps) {
  const [kind, setKind] = useState<ConnectionKind>("postgres");
  const [dbId, setDbId] = useState("");
  const [pg, setPg] = useState<PostgresConfig>(DEFAULT_POSTGRES);
  const [mysql, setMysql] = useState<MySQLConfig>(DEFAULT_MYSQL);
  const [libsql, setLibsql] = useState<LibsqlConfig>(DEFAULT_LIBSQL);
  const [oracle, setOracle] = useState<OracleConfig>(DEFAULT_ORACLE);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tested, setTested] = useState(false);
  const [tables, setTables] = useState<string[]>([]);
  const [tableDetails, setTableDetails] = useState<TableDetailsMap | undefined>(
    undefined,
  );
  const [tableQuery, setTableQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);
  const queryClient = useQueryClient();

  const reset = useCallback(() => {
    setKind("postgres");
    setDbId("");
    setPg(DEFAULT_POSTGRES);
    setMysql(DEFAULT_MYSQL);
    setLibsql(DEFAULT_LIBSQL);
    setOracle(DEFAULT_ORACLE);
    setTesting(false);
    setSaving(false);
    setTested(false);
    setTables([]);
    setTableDetails(undefined);
    setTableQuery("");
    setSelected([]);
    setError(null);
  }, []);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) reset();
      onOpenChange(next);
    },
    [reset, onOpenChange],
  );

  // Any field change invalidates the prior successful test so the user can't
  // save a config they haven't actually validated.
  const invalidateTest = useCallback(() => {
    if (tested) {
      setTested(false);
      setTables([]);
      setTableDetails(undefined);
      setTableQuery("");
      setSelected([]);
    }
  }, [tested]);

  const dbIdValid = DB_ID_PATTERN.test(dbId);

  const configReady = kind === "postgres"
    ? pg.host.length > 0 &&
      pg.database.length > 0 &&
      pg.username.length > 0 &&
      pg.password.length > 0 &&
      pg.port > 0
    : kind === "mysql"
    ? mysql.host.length > 0 &&
      mysql.database.length > 0 &&
      mysql.username.length > 0 &&
      mysql.password.length > 0 &&
      mysql.port > 0
    : kind === "oracle"
    ? oracle.host.length > 0 &&
      oracle.service_name.length > 0 &&
      oracle.username.length > 0 &&
      oracle.password.length > 0 &&
      oracle.port > 0
    : libsql.url.length > 0 && libsql.auth_token.length > 0;

  const canTest = dbIdValid && configReady && !testing && !saving;
  // Oracle additionally requires at least one selectable table picked.
  const canSave = canTest && tested && (kind !== "oracle" || selected.length > 0);

  const requestBody = (forSave: boolean) => {
    const config =
      kind === "postgres"
        ? pg
        : kind === "mysql"
        ? mysql
        : kind === "oracle"
        ? oracle
        : libsql;
    // A full "select all" is stored as null (all tables, future-proof);
    // a partial selection is stored as an explicit allowlist.
    const selectable =
      kind === "oracle" && tested ? selectableTables(tables, tableDetails) : [];
    const selected_tables =
      kind === "oracle" && forSave
        ? selected.length >= selectable.length
          ? null
          : selected
        : undefined;
    return { db_id: dbId, kind, config, selected_tables };
  };

  const handleTest = async () => {
    setError(null);
    setTesting(true);
    try {
      const result = await testConnection(requestBody(false));
      if (result.ok) {
        setTested(true);
        setTables(result.tables);
        if (kind === "oracle") {
          setTableDetails(result.details ?? {});
          // Default to everything selectable (select-all).
          setSelected(selectableTables(result.tables, result.details));
        }
        toast.success(
          `Connection OK — found ${result.tables.length} table${result.tables.length === 1 ? "" : "s"}`,
        );
      } else {
        setTested(false);
        setTables([]);
        setTableDetails(undefined);
        setSelected([]);
        setError(result.error);
      }
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      const result = await createConnection(requestBody(true));
      if (result.ok) {
        toast.success(`Connected as "${result.db_id}"`);
        setSelectedDbId(result.db_id);
        void queryClient.invalidateQueries({ queryKey: ["databases", "list"] });
        onConnectSuccess?.(result.db_id);
        handleOpenChange(false);
      } else {
        setError(result.error);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plug className="size-4" />
            Connect a database
          </DialogTitle>
          <DialogDescription>
            Point InsightXpert at your existing Postgres, MySQL, Oracle, or
            libSQL/Turso database. Credentials are encrypted at rest. Queries
            run in read-only mode (we strongly recommend a read-only role on
            your side too).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="conn-db-id">Name</Label>
            <Input
              id="conn-db-id"
              value={dbId}
              onChange={(e) => {
                setDbId(e.target.value);
                invalidateTest();
              }}
              placeholder="e.g. prod_analytics"
              maxLength={64}
              disabled={testing || saving}
              aria-invalid={dbId.length > 0 && !dbIdValid}
            />
            <p className="text-[11px] text-muted-foreground">
              Lowercase letters, digits, underscore, hyphen. Used as the
              identifier in chats and the SQL pipeline.
            </p>
          </div>

          <Tabs
            value={kind}
            onValueChange={(v) => {
              setKind(v as ConnectionKind);
              invalidateTest();
            }}
          >
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="postgres">Postgres</TabsTrigger>
              <TabsTrigger value="mysql">MySQL</TabsTrigger>
              <TabsTrigger value="oracle">Oracle</TabsTrigger>
              <TabsTrigger value="libsql">libSQL</TabsTrigger>
            </TabsList>

            <TabsContent value="postgres" className="space-y-3 pt-3">
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="pg-host">Host</Label>
                  <Input
                    id="pg-host"
                    value={pg.host}
                    onChange={(e) => {
                      setPg({ ...pg, host: e.target.value });
                      invalidateTest();
                    }}
                    placeholder="db.example.com"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="pg-port">Port</Label>
                  <Input
                    id="pg-port"
                    type="number"
                    value={pg.port}
                    onChange={(e) => {
                      setPg({ ...pg, port: Number(e.target.value) || 0 });
                      invalidateTest();
                    }}
                    disabled={testing || saving}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="pg-db">Database</Label>
                <Input
                  id="pg-db"
                  value={pg.database}
                  onChange={(e) => {
                    setPg({ ...pg, database: e.target.value });
                    invalidateTest();
                  }}
                  placeholder="prod"
                  disabled={testing || saving}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="pg-user">Username</Label>
                  <Input
                    id="pg-user"
                    value={pg.username}
                    onChange={(e) => {
                      setPg({ ...pg, username: e.target.value });
                      invalidateTest();
                    }}
                    autoComplete="off"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="pg-pass">Password</Label>
                  <Input
                    id="pg-pass"
                    type="password"
                    value={pg.password}
                    onChange={(e) => {
                      setPg({ ...pg, password: e.target.value });
                      invalidateTest();
                    }}
                    autoComplete="new-password"
                    disabled={testing || saving}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="pg-ssl">SSL mode</Label>
                  <Select
                    value={pg.ssl_mode}
                    onValueChange={(v) => {
                      setPg({ ...pg, ssl_mode: v as PostgresConfig["ssl_mode"] });
                      invalidateTest();
                    }}
                    disabled={testing || saving}
                  >
                    <SelectTrigger id="pg-ssl">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="require">require</SelectItem>
                      <SelectItem value="prefer">prefer</SelectItem>
                      <SelectItem value="allow">allow</SelectItem>
                      <SelectItem value="disable">disable</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="pg-schema">Schema</Label>
                  <Input
                    id="pg-schema"
                    value={pg.schema}
                    onChange={(e) => {
                      setPg({ ...pg, schema: e.target.value });
                      invalidateTest();
                    }}
                    placeholder="public"
                    disabled={testing || saving}
                  />
                </div>
              </div>
            </TabsContent>

            <TabsContent value="mysql" className="space-y-3 pt-3">
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="my-host">Host</Label>
                  <Input
                    id="my-host"
                    value={mysql.host}
                    onChange={(e) => {
                      setMysql({ ...mysql, host: e.target.value });
                      invalidateTest();
                    }}
                    placeholder="db.example.com"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="my-port">Port</Label>
                  <Input
                    id="my-port"
                    type="number"
                    value={mysql.port}
                    onChange={(e) => {
                      setMysql({ ...mysql, port: Number(e.target.value) || 0 });
                      invalidateTest();
                    }}
                    disabled={testing || saving}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="my-db">Database</Label>
                <Input
                  id="my-db"
                  value={mysql.database}
                  onChange={(e) => {
                    setMysql({ ...mysql, database: e.target.value });
                    invalidateTest();
                  }}
                  placeholder="analytics"
                  disabled={testing || saving}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="my-user">Username</Label>
                  <Input
                    id="my-user"
                    value={mysql.username}
                    onChange={(e) => {
                      setMysql({ ...mysql, username: e.target.value });
                      invalidateTest();
                    }}
                    autoComplete="off"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="my-pass">Password</Label>
                  <Input
                    id="my-pass"
                    type="password"
                    value={mysql.password}
                    onChange={(e) => {
                      setMysql({ ...mysql, password: e.target.value });
                      invalidateTest();
                    }}
                    autoComplete="new-password"
                    disabled={testing || saving}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="my-ssl">SSL</Label>
                  <Select
                    value={mysql.ssl_enabled ? "enabled" : "disabled"}
                    onValueChange={(v) => {
                      setMysql({ ...mysql, ssl_enabled: v === "enabled" });
                      invalidateTest();
                    }}
                    disabled={testing || saving}
                  >
                    <SelectTrigger id="my-ssl">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="enabled">Enabled</SelectItem>
                      <SelectItem value="disabled">Disabled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="my-charset">Charset</Label>
                  <Select
                    value={mysql.charset}
                    onValueChange={(v) => {
                      setMysql({ ...mysql, charset: v });
                      invalidateTest();
                    }}
                    disabled={testing || saving}
                  >
                    <SelectTrigger id="my-charset">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="utf8mb4">utf8mb4</SelectItem>
                      <SelectItem value="utf8">utf8</SelectItem>
                      <SelectItem value="latin1">latin1</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="oracle" className="space-y-3 pt-3">
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2 space-y-1.5">
                  <Label htmlFor="ora-host">Host</Label>
                  <Input
                    id="ora-host"
                    value={oracle.host}
                    onChange={(e) => {
                      setOracle({ ...oracle, host: e.target.value });
                      invalidateTest();
                    }}
                    placeholder="db.example.com"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ora-port">Port</Label>
                  <Input
                    id="ora-port"
                    type="number"
                    value={oracle.port}
                    onChange={(e) => {
                      setOracle({ ...oracle, port: Number(e.target.value) || 0 });
                      invalidateTest();
                    }}
                    disabled={testing || saving}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="ora-service">Service name</Label>
                  <Input
                    id="ora-service"
                    value={oracle.service_name}
                    onChange={(e) => {
                      setOracle({ ...oracle, service_name: e.target.value });
                      invalidateTest();
                    }}
                    placeholder="ORCLPDB"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ora-schema">Schema (optional)</Label>
                  <Input
                    id="ora-schema"
                    value={oracle.schema}
                    onChange={(e) => {
                      setOracle({ ...oracle, schema: e.target.value });
                      invalidateTest();
                    }}
                    placeholder="defaults to your user"
                    disabled={testing || saving}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="ora-user">Username</Label>
                  <Input
                    id="ora-user"
                    value={oracle.username}
                    onChange={(e) => {
                      setOracle({ ...oracle, username: e.target.value });
                      invalidateTest();
                    }}
                    autoComplete="off"
                    disabled={testing || saving}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ora-pass">Password</Label>
                  <Input
                    id="ora-pass"
                    type="password"
                    value={oracle.password}
                    onChange={(e) => {
                      setOracle({ ...oracle, password: e.target.value });
                      invalidateTest();
                    }}
                    autoComplete="new-password"
                    disabled={testing || saving}
                  />
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Thin-mode connection, no Oracle client needed. Test the
                connection, then pick which tables to expose below.
              </p>
            </TabsContent>

            <TabsContent value="libsql" className="space-y-3 pt-3">
              <div className="space-y-1.5">
                <Label htmlFor="ls-url">libSQL URL</Label>
                <Input
                  id="ls-url"
                  value={libsql.url}
                  onChange={(e) => {
                    setLibsql({ ...libsql, url: e.target.value });
                    invalidateTest();
                  }}
                  placeholder="libsql://my-db-org.turso.io"
                  disabled={testing || saving}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ls-token">Auth token</Label>
                <Input
                  id="ls-token"
                  type="password"
                  value={libsql.auth_token}
                  onChange={(e) => {
                    setLibsql({ ...libsql, auth_token: e.target.value });
                    invalidateTest();
                  }}
                  autoComplete="new-password"
                  disabled={testing || saving}
                />
                <p className="text-[11px] text-muted-foreground">
                  Token must have at least read access. We never expose it
                  back to the browser after save.
                </p>
              </div>
            </TabsContent>
          </Tabs>

          {error && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-2.5 text-xs">
              <AlertCircle className="size-3.5 mt-0.5 shrink-0 text-destructive" />
              <span className="text-destructive">{error}</span>
            </div>
          )}

          {tested && tables.length > 0 && kind !== "oracle" && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs">
              <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 font-medium">
                <CheckCircle2 className="size-3.5" />
                Connection verified — {tables.length} table
                {tables.length === 1 ? "" : "s"} discovered
              </div>
              <div className="mt-1.5 max-h-24 overflow-auto font-mono text-[11px] text-muted-foreground">
                {tables.slice(0, 50).join(", ")}
                {tables.length > 50 ? `, …+${tables.length - 50} more` : ""}
              </div>
            </div>
          )}

          {tested && kind === "oracle" && tables.length > 0 && (
            <OracleTablePicker
              tables={tables}
              details={tableDetails}
              query={tableQuery}
              onQueryChange={setTableQuery}
              selected={selected}
              onToggle={(name) => setSelected((prev) => toggleSelection(prev, name))}
              onSelectAll={(visible) =>
                setSelected((prev) => selectAllVisible(prev, visible))
              }
              onClear={(visible) =>
                setSelected((prev) => clearVisible(prev, visible))
              }
              disabled={testing || saving}
            />
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={testing || saving}
          >
            Cancel
          </Button>
          <Button
            variant="secondary"
            onClick={handleTest}
            disabled={!canTest}
          >
            {testing ? (
              <>
                <Loader2 className="size-3.5 mr-1.5 animate-spin" />
                Testing…
              </>
            ) : (
              "Test connection"
            )}
          </Button>
          <Button onClick={handleSave} disabled={!canSave}>
            {saving ? (
              <>
                <Loader2 className="size-3.5 mr-1.5 animate-spin" />
                Saving…
              </>
            ) : (
              "Save"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface OracleTablePickerProps {
  tables: string[];
  details: TableDetailsMap | undefined;
  query: string;
  onQueryChange: (q: string) => void;
  selected: string[];
  onToggle: (name: string) => void;
  onSelectAll: (visible: string[]) => void;
  onClear: (visible: string[]) => void;
  disabled: boolean;
}

/**
 * Table picker for Oracle connections — the whole DB is imported, but the
 * user chooses which tables to expose. Search filters client-side, Select
 * all / Clear operate on the visible (filtered) rows, and tables with
 * Phase-1-unsupported column types (BLOB/RAW) are shown disabled with the
 * reason. Row counts are exact COUNT(*) values from the test response
 * ("—" when a count timed out); result-set fetching stays capped at the
 * server row limit regardless.
 */
function OracleTablePicker({
  tables,
  details,
  query,
  onQueryChange,
  selected,
  onToggle,
  onSelectAll,
  onClear,
  disabled,
}: OracleTablePickerProps) {
  const visible = filterTables(tables, query);
  const visibleSelectable = visible.filter((t) => !isUnsupported(details, t));
  const allVisibleSelected =
    visibleSelectable.length > 0 &&
    visibleSelectable.every((t) => selected.includes(t));

  return (
    <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs">
      <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 font-medium">
        <CheckCircle2 className="size-3.5" />
        Connection verified — pick tables ({selected.length} of {tables.length}{" "}
        selected)
      </div>

      <div className="mt-2 flex items-center gap-2">
        <Input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search tables…"
          className="h-7 text-xs"
          disabled={disabled}
          aria-label="Search tables"
        />
        <Button
          variant="outline"
          size="sm"
          className="h-7 shrink-0 text-xs"
          onClick={() => onSelectAll(visibleSelectable)}
          disabled={disabled || allVisibleSelected}
        >
          Select all
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 shrink-0 text-xs"
          onClick={() => onClear(visible)}
          disabled={disabled || selected.length === 0}
        >
          Clear
        </Button>
      </div>

      <div className="mt-1.5 max-h-44 overflow-auto rounded border border-border/60 bg-background/60">
        {visible.length === 0 && (
          <div className="px-2.5 py-3 text-[11px] text-muted-foreground">
            No tables match “{query}”.
          </div>
        )}
        {visible.map((name) => {
          const blocked = isUnsupported(details, name);
          const info = details?.[name];
          return (
            <label
              key={name}
              className={`flex items-center gap-2 px-2.5 py-1.5 text-[11px] ${
                blocked
                  ? "cursor-not-allowed opacity-50"
                  : "cursor-pointer hover:bg-accent/50"
              }`}
              title={
                blocked
                  ? `Unsupported in v1: ${(info?.unsupported_columns ?? []).join(", ")}`
                  : undefined
              }
            >
              <input
                type="checkbox"
                checked={selected.includes(name)}
                disabled={disabled || blocked}
                onChange={() => onToggle(name)}
                className="size-3.5 shrink-0 accent-primary"
                aria-label={`Select table ${name}`}
              />
              <span className="flex-1 truncate font-mono">{name}</span>
              {blocked ? (
                <span className="shrink-0 text-destructive">BLOB/RAW</span>
              ) : (
                <span className="shrink-0 text-muted-foreground">
                  {formatRowCount(info?.row_count ?? null)}
                  {info !== undefined ? ` · ${info.column_count} cols` : ""}
                </span>
              )}
            </label>
          );
        })}
      </div>
      {selected.length === 0 && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          Select at least one table to save this connection.
        </p>
      )}
    </div>
  );
}
