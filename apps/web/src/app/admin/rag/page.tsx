"use client";

// Admin RAG tab. Today the only surface is a destructive "clear all learned
// QA pairs" action. The backend returns { deleted, count }, where count
// may be null when the provider can't report an exact number — in that
// case we toast a generic "Cleared" message.

import { DatabaseZap } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useClearQaPairs } from "@/hooks/use-admin-rag";
import { useState } from "react";

export default function RagPage() {
  const clear = useClearQaPairs();
  const [open, setOpen] = useState(false);

  async function handleConfirm() {
    try {
      const res = await clear.mutateAsync();
      if (res.count != null) {
        toast.success(`Cleared ${res.count} QA pair${res.count === 1 ? "" : "s"}.`);
      } else {
        toast.success("Cleared.");
      }
      setOpen(false);
    } catch (err) {
      toast.error(
        `Failed to clear: ${err instanceof Error ? err.message : "unknown"}`,
      );
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">RAG</h2>
        <p className="text-sm text-muted-foreground">
          Manage learned question–SQL pairs and other RAG content.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card p-6">
        <div className="flex items-start gap-3">
          <DatabaseZap className="size-5 shrink-0 text-muted-foreground" />
          <div className="space-y-1">
            <h3 className="text-sm font-semibold">Learned QA pairs</h3>
            <p className="max-w-2xl text-xs text-muted-foreground">
              The RAG layer stores successful question–SQL pairs so future
              questions can be answered with learned context. Clear them if
              the store has been poisoned, if you want to re-learn from
              scratch, or if you&apos;re changing schemas and old pairs are
              misleading the linker.
            </p>
          </div>
        </div>

        <div>
          <Button
            variant="destructive"
            onClick={() => setOpen(true)}
            disabled={clear.isPending}
          >
            Clear all learned QA pairs
          </Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clear all learned QA pairs?</DialogTitle>
            <DialogDescription>
              This deletes every stored question–SQL pair across all users
              and databases. The action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={clear.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirm}
              disabled={clear.isPending}
            >
              {clear.isPending ? "Clearing…" : "Clear all"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
