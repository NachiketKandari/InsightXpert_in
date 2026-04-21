"use client";

import { useCallback, useEffect } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAutomationStore } from "@/stores/automation-store";
import { AutomationList } from "@/components/automations/automation-list";
import { NewAutomationDialog } from "@/components/automations/new-automation-dialog";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { AUTOMATIONS_ENABLED } from "@/lib/automations/feature-flag";

export default function AutomationsPage() {
  // Feature-flag gate — when disabled, render Next 404.
  if (!AUTOMATIONS_ENABLED) {
    notFound();
  }

  const deleteAutomation = useAutomationStore((s) => s.deleteAutomation);
  const dialogOpen = useAutomationStore((s) => s.newAutomationDialogOpen);
  const openDialog = useAutomationStore((s) => s.openNewAutomationDialog);
  const closeDialog = useAutomationStore((s) => s.closeNewAutomationDialog);
  const { confirm, ConfirmDialog } = useConfirm();

  // If the chat flow deep-linked us here with conversation context, toast a
  // note and open the dialog — a placeholder until the Phase C2 builder lands.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("conversationId")) {
      openDialog();
    }
  }, [openDialog]);

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
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 glass border-b border-border px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-5xl items-center gap-3">
          <Link href="/">
            <Button variant="ghost" size="icon" className="size-9">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <h1 className="text-lg font-semibold">Automations</h1>
          <div className="ml-auto">
            <Button size="sm" onClick={openDialog}>
              <Plus className="size-4 mr-1.5" />
              New automation
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <AutomationList onDelete={handleDelete} onNew={openDialog} />
      </main>

      <ConfirmDialog />
      <NewAutomationDialog open={dialogOpen} onOpenChange={(v) => (v ? openDialog() : closeDialog())} />
    </div>
  );
}
