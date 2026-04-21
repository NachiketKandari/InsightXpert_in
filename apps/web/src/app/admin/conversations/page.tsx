"use client";

// Conversations admin tab — stub. The backend doesn't expose
// /api/v1/admin/conversations/* yet; the existing conversation-viewer
// component is ready to render full chunk traces as soon as that surface
// lands. See docs/deferred-features.md.

import Link from "next/link";
import { MessageSquare } from "lucide-react";

export default function ConversationsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Conversations</h2>
        <p className="text-sm text-muted-foreground">
          Per-user chat history with full chunk traces.
        </p>
      </div>
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-card p-10 text-center">
        <MessageSquare className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Backend endpoint not yet implemented</p>
        <p className="max-w-md text-xs text-muted-foreground">
          The admin conversations API is deferred in this cluster. The frontend
          conversation-viewer component is already in place and will be wired up
          once <code>/api/v1/admin/conversations</code> ships. Track status in{" "}
          <Link href="/docs/deferred-features.md" className="underline">
            docs/deferred-features.md
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
