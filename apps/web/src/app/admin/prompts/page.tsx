"use client";

// Prompts admin tab — stub. The backend doesn't expose /api/v1/admin/prompts
// in Phase B3. The fork's original prompts editor (see archive/
// legacy-admin-page.tsx.bak) can be re-integrated once the endpoint ships.

import Link from "next/link";
import { FileText } from "lucide-react";

export default function PromptsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Prompts</h2>
        <p className="text-sm text-muted-foreground">
          Edit the Jinja2 system prompts used by agents.
        </p>
      </div>
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-card p-10 text-center">
        <FileText className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Backend endpoint not yet implemented</p>
        <p className="max-w-md text-xs text-muted-foreground">
          The admin prompts API is deferred in this cluster. Track status in{" "}
          <Link href="/docs/deferred-features.md" className="underline">
            docs/deferred-features.md
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
