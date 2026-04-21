"use client";

// Conversations admin tab. Two-pane layout:
//   Left  — cursor-paginated list (filter by user / db), click to select.
//   Right — selected conversation detail with full chunk traces.
//
// For assistant messages the backend returns `chunks_json` already parsed to
// a ChatChunk[]. We pull out orchestrator_plan / agent_trace /
// enrichment_trace sidecars and pass them to ChunkRenderer so the existing
// ThinkingTrace surfaces when the `insight` chunk renders.

import { useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChunkRenderer } from "@/components/chunks/chunk-renderer";
import {
  useAdminConversations,
  useAdminConversationDetail,
  useDeleteConversation,
  type AdminConversationRow,
  type AdminMessage,
} from "@/hooks/use-admin-conversations";
import type {
  AgentTrace,
  ChatChunk,
  EnrichmentTrace,
  OrchestratorPlan,
} from "@/types/chat";

function formatTime(t: string | number): string {
  const d = typeof t === "number" ? new Date(t * (t < 1e12 ? 1000 : 1)) : new Date(t);
  if (Number.isNaN(d.getTime())) return String(t);
  return d.toLocaleString();
}

function truncate(s: string, n = 60): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

interface ExtractedTraces {
  plan: OrchestratorPlan | null;
  agentTraces: AgentTrace[];
  enrichmentTraces: EnrichmentTrace[];
}

function extractTraces(chunks: ChatChunk[]): ExtractedTraces {
  let plan: OrchestratorPlan | null = null;
  const agentTraces: AgentTrace[] = [];
  const enrichmentTraces: EnrichmentTrace[] = [];
  for (const c of chunks) {
    if (c.type === "orchestrator_plan") {
      const d = (c.data ?? {}) as Partial<OrchestratorPlan>;
      if (d && Array.isArray(d.tasks)) {
        plan = {
          reasoning: d.reasoning ?? "",
          tasks: d.tasks,
        };
      }
    } else if (c.type === "agent_trace") {
      if (c.data) agentTraces.push(c.data as unknown as AgentTrace);
    } else if (c.type === "enrichment_trace") {
      if (c.data) enrichmentTraces.push(c.data as unknown as EnrichmentTrace);
    }
  }
  return { plan, agentTraces, enrichmentTraces };
}

export default function ConversationsPage() {
  const [userFilter, setUserFilter] = useState("");
  const [dbFilter, setDbFilter] = useState("");
  const [appliedUser, setAppliedUser] = useState("");
  const [appliedDb, setAppliedDb] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filters = useMemo(
    () => ({
      ...(appliedUser ? { user_id: appliedUser } : {}),
      ...(appliedDb ? { db_id: appliedDb } : {}),
    }),
    [appliedUser, appliedDb],
  );

  const list = useAdminConversations(filters);
  const detail = useAdminConversationDetail(selectedId);
  const del = useDeleteConversation();

  const rows: AdminConversationRow[] = useMemo(
    () => list.data?.pages.flatMap((p) => p.rows) ?? [],
    [list.data],
  );

  function applyFilters() {
    setAppliedUser(userFilter.trim());
    setAppliedDb(dbFilter.trim());
  }

  function resetFilters() {
    setUserFilter("");
    setDbFilter("");
    setAppliedUser("");
    setAppliedDb("");
  }

  async function handleDelete() {
    if (!selectedId) return;
    if (!window.confirm("Permanently delete this conversation?")) return;
    try {
      await del.mutateAsync({ id: selectedId });
      toast.success("Conversation deleted.");
      setSelectedId(null);
    } catch {
      toast.error("Failed to delete conversation.");
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Conversations</h2>
        <p className="text-sm text-muted-foreground">
          Per-user chat history with full chunk traces.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[22rem_1fr]">
        {/* ---------- Left pane: list + filters ---------- */}
        <div className="space-y-3">
          <div className="space-y-2 rounded-lg border border-border bg-card p-3">
            <Input
              placeholder="Filter by user_id"
              value={userFilter}
              onChange={(e) => setUserFilter(e.target.value)}
            />
            <Input
              placeholder="Filter by db_id"
              value={dbFilter}
              onChange={(e) => setDbFilter(e.target.value)}
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={applyFilters} className="flex-1">
                Apply
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={resetFilters}
                className="flex-1"
              >
                Reset
              </Button>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card">
            {list.isLoading && (
              <div className="flex items-center justify-center py-8">
                <div className="h-5 w-5 animate-spin rounded-full border-b-2 border-primary" />
              </div>
            )}
            {list.error && (
              <div className="p-4 text-sm text-destructive">
                Failed to load conversations.
              </div>
            )}
            {!list.isLoading && rows.length === 0 && (
              <div className="p-6 text-center text-sm text-muted-foreground">
                No conversations.
              </div>
            )}

            <ul className="divide-y divide-border/60">
              {rows.map((r) => (
                <li key={r.id}>
                  <button
                    onClick={() => setSelectedId(r.id)}
                    className={`w-full px-3 py-2 text-left transition-colors hover:bg-muted/50 ${
                      selectedId === r.id ? "bg-muted/70" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span className="truncate">{r.user_email}</span>
                      <span>{r.message_count} msg</span>
                    </div>
                    <div className="truncate text-sm font-medium">
                      {truncate(r.title || "(untitled)", 46)}
                    </div>
                    <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                      <span className="truncate font-mono">{r.db_id ?? "—"}</span>
                      <span>{formatTime(r.updated_at)}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>

            {list.hasNextPage && (
              <div className="border-t border-border p-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={() => void list.fetchNextPage()}
                  disabled={list.isFetchingNextPage}
                >
                  {list.isFetchingNextPage ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* ---------- Right pane: detail ---------- */}
        <div className="rounded-lg border border-border bg-card">
          {!selectedId && (
            <div className="flex h-80 items-center justify-center text-sm text-muted-foreground">
              Select a conversation.
            </div>
          )}

          {selectedId && detail.isLoading && (
            <div className="flex h-80 items-center justify-center">
              <div className="h-5 w-5 animate-spin rounded-full border-b-2 border-primary" />
            </div>
          )}

          {selectedId && detail.error && (
            <div className="p-4 text-sm text-destructive">
              Failed to load conversation.
            </div>
          )}

          {selectedId && detail.data && (
            <ConversationDetailView
              data={detail.data}
              onDelete={handleDelete}
              deleting={del.isPending}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function ConversationDetailView({
  data,
  onDelete,
  deleting,
}: {
  data: NonNullable<ReturnType<typeof useAdminConversationDetail>["data"]>;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border p-4">
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">
            {data.user_email} · <span className="font-mono">{data.db_id ?? "—"}</span>
          </div>
          <h3 className="truncate text-base font-semibold">
            {data.title || "(untitled)"}
          </h3>
          <div className="text-xs text-muted-foreground">
            Updated {formatTime(data.updated_at)}
          </div>
        </div>
        <Button
          variant="destructive"
          size="sm"
          onClick={onDelete}
          disabled={deleting}
          className="gap-1"
        >
          <Trash2 className="size-3.5" />
          Delete
        </Button>
      </div>

      <div className="space-y-4 p-4">
        {data.messages.length === 0 && (
          <div className="py-6 text-center text-sm text-muted-foreground">
            No messages in this conversation.
          </div>
        )}
        {data.messages.map((m) => (
          <MessageCard key={m.id} message={m} />
        ))}
      </div>
    </div>
  );
}

function MessageCard({ message }: { message: AdminMessage }) {
  const chunks = Array.isArray(message.chunks_json) ? message.chunks_json : [];
  const { plan, agentTraces, enrichmentTraces } = useMemo(
    () => extractTraces(chunks),
    [chunks],
  );

  const isUser = message.role === "user";

  return (
    <div
      className={`rounded-lg border p-3 ${
        isUser
          ? "border-border/70 bg-muted/30"
          : "border-border bg-background"
      }`}
    >
      <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
        <span className="font-medium uppercase tracking-wide">
          {message.role}
        </span>
        <span>{formatTime(message.created_at)}</span>
      </div>

      {isUser ? (
        <div className="whitespace-pre-wrap text-sm">{message.content}</div>
      ) : chunks.length > 0 ? (
        <div className="space-y-2">
          {chunks.map((c, i) => (
            <ChunkRenderer
              key={i}
              chunk={c}
              isComplete
              orchestratorPlan={plan}
              agentTraces={agentTraces}
              enrichmentTraces={enrichmentTraces}
            />
          ))}
        </div>
      ) : (
        <div className="whitespace-pre-wrap text-sm">{message.content}</div>
      )}

      {(message.tokens_in != null || message.tokens_out != null) && (
        <div className="mt-2 flex gap-3 text-[10px] text-muted-foreground">
          {message.tokens_in != null && <span>in: {message.tokens_in}</span>}
          {message.tokens_out != null && <span>out: {message.tokens_out}</span>}
        </div>
      )}
    </div>
  );
}
