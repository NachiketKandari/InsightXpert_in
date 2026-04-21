"use client";

// Admin Prompts tab. Two-pane editor:
//   Left  — list of prompt names + source badge ("db" / "file") and mtime.
//   Right — selected prompt editor with:
//             * description field
//             * monospace textarea for active content
//             * collapsible "file default" showing file_content for reference
//             * Save (PUT) / Reset (POST /reset) / Delete (only if source=db)
// B3 spec explicitly says NOT to pull Monaco in here — SQL drawer Monaco
// lands in Task 17.

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  useAdminPrompt,
  useAdminPrompts,
  useDeletePrompt,
  useResetPrompt,
  useSavePrompt,
  type PromptSource,
} from "@/hooks/use-admin-prompts";

function formatTime(t: string | number | null | undefined): string {
  if (t == null || t === "") return "—";
  const d =
    typeof t === "number" ? new Date(t * (t < 1e12 ? 1000 : 1)) : new Date(t);
  if (Number.isNaN(d.getTime())) return String(t);
  return d.toLocaleString();
}

function sourceBadgeClass(source: PromptSource): string {
  return source === "db"
    ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
    : "bg-muted text-muted-foreground";
}

export default function PromptsPage() {
  const list = useAdminPrompts();
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useAdminPrompt(selected);
  const save = useSavePrompt();
  const del = useDeletePrompt();
  const reset = useResetPrompt();

  const [content, setContent] = useState("");
  const [description, setDescription] = useState("");
  const [showFileDefault, setShowFileDefault] = useState(false);

  useEffect(() => {
    if (detail.data) {
      setContent(detail.data.content ?? "");
      setDescription(detail.data.description ?? "");
    }
  }, [detail.data]);

  async function handleSave() {
    if (!selected) return;
    try {
      await save.mutateAsync({
        name: selected,
        content,
        description: description || null,
      });
      toast.success(`Saved ${selected}.`);
    } catch (err) {
      toast.error(
        `Failed to save: ${err instanceof Error ? err.message : "unknown"}`,
      );
    }
  }

  async function handleReset() {
    if (!selected) return;
    if (
      !window.confirm(
        `Reset "${selected}" to the file default? Any database override for this prompt will be cleared.`,
      )
    )
      return;
    try {
      await reset.mutateAsync({ name: selected });
      toast.success(`Reset ${selected} to file default.`);
    } catch (err) {
      toast.error(
        `Failed to reset: ${err instanceof Error ? err.message : "unknown"}`,
      );
    }
  }

  async function handleDelete() {
    if (!selected) return;
    if (
      !window.confirm(
        `Delete database override for "${selected}"? The file default will take over.`,
      )
    )
      return;
    try {
      await del.mutateAsync({ name: selected });
      toast.success(`Deleted override for ${selected}.`);
    } catch (err) {
      toast.error(
        `Failed to delete: ${err instanceof Error ? err.message : "unknown"}`,
      );
    }
  }

  const canDelete = detail.data?.source === "db";
  const dirty =
    detail.data != null &&
    (content !== (detail.data.content ?? "") ||
      (description || "") !== (detail.data.description ?? ""));

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Prompts</h2>
        <p className="text-sm text-muted-foreground">
          Edit the system prompts used by agents. Database overrides take
          precedence over the file defaults; reset clears the override.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[18rem_1fr]">
        {/* ---------- Left: list ---------- */}
        <div className="rounded-lg border border-border bg-card">
          {list.isLoading && (
            <div className="flex items-center justify-center py-8">
              <div className="h-5 w-5 animate-spin rounded-full border-b-2 border-primary" />
            </div>
          )}
          {list.error && (
            <div className="p-4 text-sm text-destructive">
              Failed to load prompts.
            </div>
          )}
          {!list.isLoading && (list.data?.length ?? 0) === 0 && (
            <div className="p-6 text-center text-sm text-muted-foreground">
              No prompts found.
            </div>
          )}
          <ul className="divide-y divide-border/60">
            {list.data?.map((p) => (
              <li key={p.name}>
                <button
                  onClick={() => setSelected(p.name)}
                  className={`w-full px-3 py-2 text-left transition-colors hover:bg-muted/50 ${
                    selected === p.name ? "bg-muted/70" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-mono text-sm">{p.name}</span>
                    <Badge className={`text-[10px] ${sourceBadgeClass(p.source)}`}>
                      {p.source}
                    </Badge>
                  </div>
                  {p.source === "db" && (
                    <div className="text-[10px] text-muted-foreground">
                      {formatTime(p.updated_at)}
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>

        {/* ---------- Right: editor ---------- */}
        <div className="rounded-lg border border-border bg-card">
          {!selected && (
            <div className="flex h-80 items-center justify-center text-sm text-muted-foreground">
              Select a prompt.
            </div>
          )}
          {selected && detail.isLoading && (
            <div className="flex h-80 items-center justify-center">
              <div className="h-5 w-5 animate-spin rounded-full border-b-2 border-primary" />
            </div>
          )}
          {selected && detail.error && (
            <div className="p-4 text-sm text-destructive">
              Failed to load prompt.
            </div>
          )}

          {selected && detail.data && (
            <div className="space-y-4 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-mono text-base font-semibold">
                      {detail.data.name}
                    </h3>
                    <Badge
                      className={`text-[10px] ${sourceBadgeClass(
                        detail.data.source,
                      )}`}
                    >
                      {detail.data.source}
                    </Badge>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Updated {formatTime(detail.data.updated_at)}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    onClick={handleSave}
                    disabled={save.isPending || !dirty}
                  >
                    {save.isPending ? "Saving…" : "Save"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleReset}
                    disabled={reset.isPending}
                  >
                    {reset.isPending ? "Resetting…" : "Reset"}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={handleDelete}
                    disabled={!canDelete || del.isPending}
                    title={
                      canDelete
                        ? "Delete database override"
                        : "No database override to delete"
                    }
                  >
                    {del.isPending ? "Deleting…" : "Delete"}
                  </Button>
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prompt-description">Description</Label>
                <Input
                  id="prompt-description"
                  placeholder="Optional description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="prompt-content">Active content</Label>
                <Textarea
                  id="prompt-content"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  className="min-h-[24rem] font-mono text-xs"
                  spellCheck={false}
                />
              </div>

              {detail.data.file_content != null && (
                <Collapsible
                  open={showFileDefault}
                  onOpenChange={setShowFileDefault}
                >
                  <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-left text-sm hover:bg-muted/50">
                    {showFileDefault ? (
                      <ChevronDown className="size-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-4 text-muted-foreground" />
                    )}
                    <span className="font-medium">File default</span>
                    <span className="ml-1 text-xs text-muted-foreground">
                      (read-only reference)
                    </span>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="mt-2">
                    <pre className="max-h-96 overflow-auto rounded-md border border-border bg-muted/20 p-3 font-mono text-xs">
                      {detail.data.file_content}
                    </pre>
                  </CollapsibleContent>
                </Collapsible>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
