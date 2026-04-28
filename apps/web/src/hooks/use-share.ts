"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createShare, deleteShare, getShare, type ShareMeta } from "@/lib/share-api";

const shareKey = (conversationId: string) => ["share", conversationId] as const;

export function useShare(conversationId: string | null) {
  return useQuery({
    queryKey: shareKey(conversationId ?? ""),
    enabled: !!conversationId,
    queryFn: () => getShare(conversationId!),
    staleTime: 30_000,
    gcTime: 5 * 60_000,
  });
}

export function useCreateShare(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (acknowledgeUploaded: boolean) =>
      createShare(conversationId, acknowledgeUploaded),
    onSuccess: (result) => {
      if (result.ok) {
        qc.setQueryData<ShareMeta>(shareKey(conversationId), result.meta);
      }
    },
  });
}

export function useRevokeShare(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => deleteShare(conversationId),
    onSuccess: () => {
      qc.setQueryData<ShareMeta | null>(shareKey(conversationId), null);
    },
  });
}
