"use client";

// RAG admin tab — stub. The backend doesn't expose /api/v1/admin/rag/*
// in Phase B3. Ships as an empty state linking to docs/deferred-features.md.

import Link from "next/link";
import { DatabaseZap } from "lucide-react";

export default function RagPage() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">RAG</h2>
        <p className="text-sm text-muted-foreground">
          Manage learned question–SQL pairs and other RAG content.
        </p>
      </div>
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-card p-10 text-center">
        <DatabaseZap className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Backend endpoint not yet implemented</p>
        <p className="max-w-md text-xs text-muted-foreground">
          The admin RAG management API (clear QA pairs, inspect index) is
          deferred in this cluster. Track status in{" "}
          <Link href="/docs/deferred-features.md" className="underline">
            docs/deferred-features.md
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
