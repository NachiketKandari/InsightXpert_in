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
  type PostgresConfig,
} from "@/lib/connections/api";
import { useChatStore } from "@/stores/chat-store";

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

const DEFAULT_LIBSQL: LibsqlConfig = { url: "", auth_token: "" };

export function ConnectDbDialog({
  open,
  onOpenChange,
  onConnectSuccess,
}: ConnectDbDialogProps) {
  const [kind, setKind] = useState<ConnectionKind>("postgres");
  const [dbId, setDbId] = useState("");
  const [pg, setPg] = useState<PostgresConfig>(DEFAULT_POSTGRES);
  const [libsql, setLibsql] = useState<LibsqlConfig>(DEFAULT_LIBSQL);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tested, setTested] = useState(false);
  const [tables, setTables] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const setSelectedDbId = useChatStore((s) => s.setSelectedDbId);

  const reset = useCallback(() => {
    setKind("postgres");
    setDbId("");
    setPg(DEFAULT_POSTGRES);
    setLibsql(DEFAULT_LIBSQL);
    setTesting(false);
    setSaving(false);
    setTested(false);
    setTables([]);
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
    }
  }, [tested]);

  const dbIdValid = DB_ID_PATTERN.test(dbId);

  const configReady = kind === "postgres"
    ? pg.host.length > 0 &&
      pg.database.length > 0 &&
      pg.username.length > 0 &&
      pg.password.length > 0 &&
      pg.port > 0
    : libsql.url.length > 0 && libsql.auth_token.length > 0;

  const canTest = dbIdValid && configReady && !testing && !saving;
  const canSave = canTest && tested;

  const requestBody = () => ({
    db_id: dbId,
    kind,
    config: kind === "postgres" ? pg : libsql,
  });

  const handleTest = async () => {
    setError(null);
    setTesting(true);
    try {
      const result = await testConnection(requestBody());
      if (result.ok) {
        setTested(true);
        setTables(result.tables);
        toast.success(
          `Connection OK — found ${result.tables.length} table${result.tables.length === 1 ? "" : "s"}`,
        );
      } else {
        setTested(false);
        setTables([]);
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
      const result = await createConnection(requestBody());
      if (result.ok) {
        toast.success(`Connected as "${result.db_id}"`);
        setSelectedDbId(result.db_id);
        // Notify the dataset selector to refresh.
        if (typeof window !== "undefined") {
          window.dispatchEvent(new Event("databases-changed"));
        }
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
            Point InsightXpert at your existing Postgres or libSQL/Turso
            database. Credentials are encrypted at rest. Queries run in
            read-only mode (we strongly recommend a read-only role on your
            side too).
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
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="postgres">Postgres</TabsTrigger>
              <TabsTrigger value="libsql">libSQL / Turso</TabsTrigger>
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

          {tested && tables.length > 0 && (
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
