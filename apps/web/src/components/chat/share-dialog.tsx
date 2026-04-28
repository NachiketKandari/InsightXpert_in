"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCreateShare, useRevokeShare, useShare } from "@/hooks/use-share";

export interface ShareDialogProps {
  conversationId: string;
  dbKindHint: "bundled" | "uploaded" | "postgres" | "none" | "unknown";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ShareDialog({
  conversationId,
  dbKindHint,
  open,
  onOpenChange,
}: ShareDialogProps) {
  const { data: existing, refetch } = useShare(conversationId);
  const createMut = useCreateShare(conversationId);
  const revokeMut = useRevokeShare(conversationId);

  const [acknowledged, setAcknowledged] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) {
      setErrorMsg(null);
      setCopied(false);
    }
  }, [open]);

  const fullUrl = existing
    ? `${typeof window !== "undefined" ? window.location.origin : ""}${existing.share_url}`
    : null;

  const isPostgres = dbKindHint === "postgres";
  const isUploaded = dbKindHint === "uploaded";

  async function handleCreate() {
    setErrorMsg(null);
    const result = await createMut.mutateAsync(acknowledged);
    if (result.ok) return;
    switch (result.error.kind) {
      case "uploaded_consent_required":
        setErrorMsg("Tick the consent checkbox to share an uploaded SQLite.");
        return;
      case "postgres_refused":
        setErrorMsg(
          "Sharing chats bound to live database connections is disabled in this version.",
        );
        return;
      case "sharing_disabled":
        setErrorMsg("Sharing has been disabled for your account by an administrator.");
        return;
      default:
        setErrorMsg(result.error.message ?? "Could not create share.");
    }
  }

  async function handleRevoke() {
    setErrorMsg(null);
    await revokeMut.mutateAsync();
    await refetch();
  }

  async function handleCopy() {
    if (!fullUrl) return;
    await navigator.clipboard.writeText(fullUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share this chat</DialogTitle>
          <DialogDescription>
            A shared link is a frozen, read-only snapshot. Reasoning traces and
            internal IDs are stripped. The link expires after 90 days and can be
            revoked at any time.
          </DialogDescription>
        </DialogHeader>

        {isPostgres && (
          <p data-testid="share-postgres-block" className="text-sm text-red-600">
            This chat is bound to a live Postgres connection. Sharing live-DB
            chats is disabled in this version.
          </p>
        )}

        {!isPostgres && isUploaded && !existing && (
          <label className="flex items-start gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              data-testid="share-consent-checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
            />
            <span>
              I confirm the chat may contain rows from my uploaded SQLite and I
              want to expose those rows on a public URL.
            </span>
          </label>
        )}

        {existing ? (
          <div className="flex items-center gap-2">
            <Input data-testid="share-url-input" readOnly value={fullUrl ?? ""} />
            <Button data-testid="share-copy-btn" onClick={handleCopy}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        ) : null}

        {errorMsg && (
          <p data-testid="share-error" className="text-sm text-red-600">
            {errorMsg}
          </p>
        )}

        <DialogFooter>
          {existing ? (
            <Button
              data-testid="share-revoke-btn"
              variant="destructive"
              onClick={handleRevoke}
              disabled={revokeMut.isPending}
            >
              Revoke
            </Button>
          ) : (
            <Button
              data-testid="share-create-btn"
              onClick={handleCreate}
              disabled={
                isPostgres ||
                createMut.isPending ||
                (isUploaded && !acknowledged)
              }
            >
              {createMut.isPending ? "Creating…" : "Create share link"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
