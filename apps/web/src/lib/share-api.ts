import { z } from "zod";
import { apiFetch } from "./api";

export const ShareMetaSchema = z.object({
  token: z.string(),
  share_url: z.string(),
  created_at: z.number(),
  expires_at: z.number().nullable(),
  revoked: z.boolean(),
  view_count: z.number(),
});

export type ShareMeta = z.infer<typeof ShareMetaSchema>;

export const SharedSnapshotPublicSchema = z.object({
  title: z.string().nullable(),
  dataset_name: z.string().nullable(),
  messages: z.array(
    z.object({
      role: z.enum(["user", "assistant"]),
      content: z.string(),
      created_at: z.number(),
    }),
  ),
  created_at: z.number(),
  expires_at: z.number().nullable(),
});

export type SharedSnapshotPublic = z.infer<typeof SharedSnapshotPublicSchema>;

export type CreateShareError =
  | { kind: "uploaded_consent_required" }
  | { kind: "postgres_refused" }
  | { kind: "sharing_disabled" }
  | { kind: "unknown"; message: string };

export async function createShare(
  conversationId: string,
  acknowledgeUploaded: boolean,
): Promise<{ ok: true; meta: ShareMeta } | { ok: false; error: CreateShareError }> {
  const res = await apiFetch(`/api/v1/conversations/${conversationId}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ acknowledge_uploaded: acknowledgeUploaded }),
  });
  if (res.ok) {
    const json = await res.json();
    return { ok: true, meta: ShareMetaSchema.parse(json) };
  }
  if (res.status === 409) return { ok: false, error: { kind: "uploaded_consent_required" } };
  if (res.status === 403) {
    const text = (await res.text()).toLowerCase();
    if (text.includes("postgres") || text.includes("libsql")) {
      return { ok: false, error: { kind: "postgres_refused" } };
    }
    if (text.includes("disabled")) {
      return { ok: false, error: { kind: "sharing_disabled" } };
    }
    return { ok: false, error: { kind: "unknown", message: text } };
  }
  return { ok: false, error: { kind: "unknown", message: `HTTP ${res.status}` } };
}

export async function getShare(conversationId: string): Promise<ShareMeta | null> {
  const res = await apiFetch(`/api/v1/conversations/${conversationId}/share`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to fetch share: HTTP ${res.status}`);
  const json = await res.json();
  return ShareMetaSchema.parse(json);
}

export async function deleteShare(conversationId: string): Promise<void> {
  await apiFetch(`/api/v1/conversations/${conversationId}/share`, {
    method: "DELETE",
  });
}
