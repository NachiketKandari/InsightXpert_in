"use client";

import { useState, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { Play, AlertTriangle, Clock, Rows3, X, Loader2, Table2, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable } from "@/components/chunks/data-table";
import { ChartConfigurator } from "@/components/sql/chart-configurator";
import { apiFetch } from "@/lib/api";
import type { QueryResult, QueryError } from "@/types/api";

// Monaco is SSR-incompatible — load client-side only.
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-[160px] flex items-center justify-center text-xs text-muted-foreground">
      Loading editor…
    </div>
  ),
});

export function SqlExecutor({ onClose }: { onClose: () => void }) {
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Detect dark mode to pick Monaco theme; keeps in sync with the app theme.
  const [isDark, setIsDark] = useState<boolean>(() =>
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      setIsDark(root.classList.contains("dark"));
    });
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  const execute = useCallback(async () => {
    const trimmed = sql.trim();
    if (!trimmed || loading) return;

    setError(null);
    setResult(null);
    setLoading(true);

    try {
      const res = await apiFetch("/api/sql/execute", {
        method: "POST",
        body: JSON.stringify({ sql: trimmed }),
      });

      if (!res.ok) {
        const body: QueryError = await res.json();
        setError(body.detail || `HTTP ${res.status}`);
        return;
      }

      const data: QueryResult = await res.json();
      setResult(data);
    } catch (err) {
      setError((err as Error).message || "Network error");
    } finally {
      setLoading(false);
    }
  }, [sql, loading]);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold tracking-wide">SQL Executor</h2>
          <Badge variant="secondary" className="text-[10px]">
            Read-only
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={onClose}
        >
          <X className="size-4" />
        </Button>
      </div>

      {/* Editor */}
      <div className="px-4 pt-3 pb-2 border-b border-border">
        <div className="relative rounded-lg border border-border bg-card/50 overflow-hidden focus-within:ring-1 focus-within:ring-cyan-accent/50 focus-within:border-cyan-accent/50 transition-colors">
          <MonacoEditor
            height="160px"
            defaultLanguage="sql"
            theme={isDark ? "vs-dark" : "vs"}
            value={sql}
            onChange={(v) => setSql(v ?? "")}
            onMount={(editor, monaco) => {
              editor.addCommand(
                monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter,
                () => {
                  // Read the latest SQL directly from the editor to avoid
                  // capturing a stale closure over the `execute` callback.
                  const current = editor.getValue().trim();
                  if (!current) return;
                  void (async () => {
                    setError(null);
                    setResult(null);
                    setLoading(true);
                    try {
                      const res = await apiFetch("/api/sql/execute", {
                        method: "POST",
                        body: JSON.stringify({ sql: current }),
                      });
                      if (!res.ok) {
                        const body: QueryError = await res.json();
                        setError(body.detail || `HTTP ${res.status}`);
                        return;
                      }
                      const data: QueryResult = await res.json();
                      setResult(data);
                    } catch (err) {
                      setError((err as Error).message || "Network error");
                    } finally {
                      setLoading(false);
                    }
                  })();
                },
              );
            }}
            options={{
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 13,
              fontFamily: "var(--font-mono)",
              lineNumbers: "on",
              folding: false,
              renderLineHighlight: "none",
              padding: { top: 8, bottom: 8 },
              automaticLayout: true,
              wordWrap: "on",
            }}
          />
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-[11px] text-muted-foreground">
            {typeof navigator !== "undefined" &&
            /mac/i.test(navigator.userAgent)
              ? "\u2318"
              : "Ctrl"}
            +Enter to run
          </span>
          <Button
            size="sm"
            onClick={execute}
            disabled={!sql.trim() || loading}
            className="gap-1.5"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Play className="size-3.5" />
            )}
            Execute
          </Button>
        </div>
      </div>

      {/* Results area */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {error && (
          <div className="mx-4 mt-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 flex items-start gap-2">
            <AlertTriangle className="size-4 text-destructive shrink-0 mt-0.5" />
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        {result && (
          <div className="flex flex-col h-full">
            {result.columns.length > 0 ? (
              <Tabs defaultValue="results" className="flex flex-col flex-1 min-h-0">
                <div className="flex items-center justify-between px-4 pt-3">
                  <TabsList className="w-fit">
                    <TabsTrigger value="results" className="gap-1.5 text-xs">
                      <Table2 className="size-3" />
                      Results
                    </TabsTrigger>
                    <TabsTrigger value="visualize" className="gap-1.5 text-xs">
                      <BarChart3 className="size-3" />
                      Visualize
                    </TabsTrigger>
                  </TabsList>
                  <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Rows3 className="size-3" />
                      {result.row_count} row{result.row_count !== 1 ? "s" : ""}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="size-3" />
                      {result.execution_time_ms.toFixed(1)}ms
                    </span>
                  </div>
                </div>

                <TabsContent value="results" className="flex-1 min-h-0 mt-0 px-4 pb-4">
                  <div className="rounded-lg border border-border bg-card overflow-auto h-full">
                    <DataTable
                      columns={result.columns}
                      rows={result.rows}
                      maxHeight="none"
                      headerRowClassName="bg-card sticky top-0 z-10"
                      headerCellClassName="border-b border-border font-semibold"
                      rowClassName={(i) =>
                        i % 2 === 0
                          ? "bg-transparent hover:bg-muted/30 transition-colors"
                          : "bg-muted/10 hover:bg-muted/30 transition-colors"
                      }
                      cellClassName="border-b border-border/20"
                      tableClassName="rounded-none border-none"
                    />
                  </div>
                </TabsContent>

                <TabsContent value="visualize" className="flex-1 min-h-0 mt-0 overflow-auto px-4 pb-4">
                  <div className="rounded-lg border border-border bg-card overflow-hidden">
                    <ChartConfigurator
                      columns={result.columns}
                      rows={result.rows}
                    />
                  </div>
                </TabsContent>
              </Tabs>
            ) : (
              <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                Query executed successfully. No rows returned.
              </div>
            )}
          </div>
        )}

        {!result && !error && (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground/50 gap-2 px-4">
            <pre className="text-xs font-mono text-muted-foreground/60 m-0 leading-relaxed">
{`SELECT column FROM table
WHERE condition
LIMIT 100;`}
            </pre>
            <p className="text-xs mt-2">
              Write a query above and hit Execute
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
