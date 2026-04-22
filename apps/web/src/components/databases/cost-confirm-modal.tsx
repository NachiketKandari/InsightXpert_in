"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { ProfileCostEstimatePayload } from "@/types/database";

interface CostConfirmModalProps {
  open: boolean;
  estimate: ProfileCostEstimatePayload | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export function CostConfirmModal({
  open,
  estimate,
  onConfirm,
  onCancel,
}: CostConfirmModalProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Confirm profiling run</DialogTitle>
          <DialogDescription>
            This run will call the LLM. Review the estimate before continuing.
          </DialogDescription>
        </DialogHeader>

        <div className="px-4 pb-2">
          {estimate ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Columns</dt>
              <dd className="font-medium">{estimate.columns}</dd>

              <dt className="text-muted-foreground">Batch size</dt>
              <dd className="font-medium">{estimate.batch_size}</dd>

              <dt className="text-muted-foreground">LLM calls</dt>
              <dd className="font-medium">{estimate.total_llm_calls}</dd>

              <dt className="text-muted-foreground">Estimated time</dt>
              <dd className="font-medium">~{estimate.estimated_seconds}s</dd>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">Loading estimate…</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={!estimate}>
            Confirm &amp; run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
