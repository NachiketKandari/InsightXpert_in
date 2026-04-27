"use client";

import { useCallback } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAutomationStore } from "@/stores/automation-store";
import { AutomationList } from "@/components/automations/automation-list";
import { NewAutomationDialog } from "@/components/automations/new-automation-dialog";
import { useConfirm } from "@/components/ui/confirm-dialog";

export function AdminAutomationsClient() {
  const deleteAutomation = useAutomationStore((s) => s.deleteAutomation);
  const dialogOpen = useAutomationStore((s) => s.newAutomationDialogOpen);
  const openDialog = useAutomationStore((s) => s.openNewAutomationDialog);
  const closeDialog = useAutomationStore((s) => s.closeNewAutomationDialog);
  const { confirm, ConfirmDialog } = useConfirm();

  const handleDelete = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: "Delete automation",
        description:
          "Are you sure? This will stop all scheduled runs and cannot be undone.",
        confirmLabel: "Delete",
        variant: "destructive",
      });
      if (ok) {
        await deleteAutomation(id);
      }
    },
    [confirm, deleteAutomation],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Automations</h2>
          <p className="text-sm text-muted-foreground">
            All automations across users. Admins can delete and toggle any automation.
          </p>
        </div>
        <Button size="sm" onClick={openDialog}>
          <Plus className="size-4 mr-1.5" />
          New automation
        </Button>
      </div>

      <AutomationList onDelete={handleDelete} onNew={openDialog} />

      <ConfirmDialog />
      <NewAutomationDialog open={dialogOpen} onOpenChange={(v) => (v ? openDialog() : closeDialog())} />
    </div>
  );
}
