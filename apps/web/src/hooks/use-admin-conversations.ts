"use client";

// Admin Conversations hooks: cursor-paginated list + detail + delete.
// Backends (Phase B3 Cluster 3.5):
//   GET    /api/v1/admin/conversations/?user_id=&db_id=&cursor=&limit=50
//   GET    /api/v1/admin/conversations/{conv_id}
//   DELETE /api/v1/admin/conversations/{conv_id}

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { ChatChunk } from "@/types/chat";

export interface AdminConversationRow {
  id: string;
  user_id: string;
  user_email: string;
  db_id: string | null;
  title: string;
  message_count: number;
  created_at: string | number;
  updated_at: string | number;
}

export interface AdminMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  tokens_in?: number | null;
  tokens_out?: number | null;
  // Already parsed by the backend — list of ChatChunk-shaped objects for
  // assistant messages, or null/empty for user messages.
  chunks_json?: ChatChunk[] | null;
  created_at: string | number;
}

export interface AdminConversationDetail {
  id: string;
  user_id: string;
  user_email: string;
  db_id: string | null;
  title: string;
  created_at: string | number;
  updated_at: string | number;
  messages: AdminMessage[];
}

export interface ListFilters {
  user_id?: string;
  db_id?: string;
  limit?: number;
}

interface ListPage {
  rows: AdminConversationRow[];
  next_cursor: string | null;
}

const LIST_KEY = (f: ListFilters) => ["admin", "conversations", f] as const;
const DETAIL_KEY = (id: string) => ["admin", "conversation", id] as const;

function buildListUrl(filters: ListFilters, cursor: string | null): string {
  const params = new URLSearchParams();
  if (filters.user_id) params.set("user_id", filters.user_id);
  if (filters.db_id) params.set("db_id", filters.db_id);
  params.set("limit", String(filters.limit ?? 50));
  if (cursor) params.set("cursor", cursor);
  return `/api/v1/admin/conversations/?${params.toString()}`;
}

export function useAdminConversations(filters: ListFilters) {
  return useInfiniteQuery({
    queryKey: LIST_KEY(filters),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const res = await apiFetch(buildListUrl(filters, pageParam));
      if (!res.ok) throw new Error(`conversations_list_failed_${res.status}`);
      return (await res.json()) as ListPage;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 15_000,
  });
}

export function useAdminConversationDetail(id: string | null) {
  return useQuery({
    queryKey: DETAIL_KEY(id ?? ""),
    enabled: !!id,
    queryFn: async () => {
      const res = await apiFetch(
        `/api/v1/admin/conversations/${encodeURIComponent(id!)}`,
      );
      if (!res.ok) throw new Error(`conversation_detail_failed_${res.status}`);
      return (await res.json()) as AdminConversationDetail;
    },
    staleTime: 15_000,
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      const res = await apiFetch(
        `/api/v1/admin/conversations/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error(`delete_failed_${res.status}`);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "conversations"] });
    },
  });
}
