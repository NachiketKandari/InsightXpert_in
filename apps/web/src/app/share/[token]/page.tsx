import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { headers } from "next/headers";
import {
  SharedSnapshotPublicSchema,
  type SharedSnapshotPublic,
} from "@/lib/share-api";
import { SharedMessageList } from "@/components/share/shared-message-list";

export const metadata: Metadata = {
  robots: { index: false, follow: false, nocache: true, noarchive: true },
};

async function fetchSnapshot(token: string): Promise<SharedSnapshotPublic | null> {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const res = await fetch(`${proto}://${host}/api/v1/public/shares/${token}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  const json = await res.json();
  return SharedSnapshotPublicSchema.parse(json);
}

export default async function SharePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const snapshot = await fetchSnapshot(token);
  if (!snapshot) notFound();

  return (
    <main className="mx-auto max-w-3xl px-4 py-8" data-testid="share-page">
      <header className="mb-6 border-b pb-4">
        <h1 className="text-2xl font-semibold">
          {snapshot.title ?? "Shared chat"}
        </h1>
        {snapshot.dataset_name && (
          <p className="text-sm text-muted-foreground">
            Dataset: {snapshot.dataset_name}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Read-only snapshot — generated{" "}
          {new Date(snapshot.created_at).toLocaleDateString()}.
        </p>
      </header>
      <SharedMessageList snapshot={snapshot} />
    </main>
  );
}
