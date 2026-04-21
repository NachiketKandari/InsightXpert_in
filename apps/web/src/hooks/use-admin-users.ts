"use client";

// Admin Users CRUD hook set: list + invite + patch (role/is_active) + reset
// password + delete. Mutations optimistically update the list cache so the
// table feels instant; server errors surface via the return value so the
// caller can toast them (the backend returns 409 "last_admin" on the protected
// last-admin path — the Users page handles that).

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";

export interface AdminUser {
  id: string;
  email: string;
  role: "admin" | "user";
  is_active: boolean;
  must_change_password: boolean;
  last_seen_at: number | null;
}

export interface InviteInput {
  email: string;
  role: "admin" | "user";
}

export interface InviteResult {
  id: string;
  email: string;
  role: "admin" | "user";
  temp_password: string;
}

export interface ResetPasswordResult {
  temp_password: string;
}

const LIST_KEY = ["admin", "users"] as const;

async function fetchUsers(): Promise<AdminUser[]> {
  const res = await apiFetch("/api/v1/admin/users/");
  if (!res.ok) throw new Error(`list_failed_${res.status}`);
  return (await res.json()) as AdminUser[];
}

async function parseError(res: Response): Promise<Error> {
  let detail = "unknown";
  try {
    const body = (await res.json()) as { detail?: string };
    if (body?.detail) detail = body.detail;
  } catch {
    // non-JSON body
  }
  const err = new Error(detail);
  (err as Error & { status?: number }).status = res.status;
  return err;
}

export function useAdminUsers() {
  return useQuery({ queryKey: LIST_KEY, queryFn: fetchUsers, staleTime: 15_000 });
}

export function useInviteUser() {
  const qc = useQueryClient();
  return useMutation<InviteResult, Error, InviteInput>({
    mutationFn: async (input) => {
      const res = await apiFetch("/api/v1/admin/users/", {
        method: "POST",
        body: JSON.stringify(input),
      });
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as InviteResult;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}

export function usePatchUser() {
  const qc = useQueryClient();
  return useMutation<
    void,
    Error,
    { id: string; role?: "admin" | "user"; is_active?: boolean }
  >({
    mutationFn: async ({ id, ...rest }) => {
      const res = await apiFetch(`/api/v1/admin/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(rest),
      });
      if (!res.ok) throw await parseError(res);
    },
    onMutate: async ({ id, role, is_active }) => {
      await qc.cancelQueries({ queryKey: LIST_KEY });
      const prev = qc.getQueryData<AdminUser[]>(LIST_KEY);
      if (prev) {
        qc.setQueryData<AdminUser[]>(
          LIST_KEY,
          prev.map((u) =>
            u.id === id
              ? {
                  ...u,
                  ...(role !== undefined ? { role } : {}),
                  ...(is_active !== undefined ? { is_active } : {}),
                }
              : u,
          ),
        );
      }
      return { prev } as { prev: AdminUser[] | undefined };
    },
    onError: (_err, _vars, context) => {
      const ctx = context as { prev?: AdminUser[] } | undefined;
      if (ctx?.prev) qc.setQueryData(LIST_KEY, ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}

export function useResetPassword() {
  return useMutation<ResetPasswordResult, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      const res = await apiFetch(`/api/v1/admin/users/${id}/reset-password`, {
        method: "POST",
      });
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as ResetPasswordResult;
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, { id: string }>({
    mutationFn: async ({ id }) => {
      const res = await apiFetch(`/api/v1/admin/users/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw await parseError(res);
    },
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: LIST_KEY });
      const prev = qc.getQueryData<AdminUser[]>(LIST_KEY);
      if (prev) {
        qc.setQueryData<AdminUser[]>(
          LIST_KEY,
          prev.filter((u) => u.id !== id),
        );
      }
      return { prev } as { prev: AdminUser[] | undefined };
    },
    onError: (_err, _vars, context) => {
      const ctx = context as { prev?: AdminUser[] } | undefined;
      if (ctx?.prev) qc.setQueryData(LIST_KEY, ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: LIST_KEY });
    },
  });
}
