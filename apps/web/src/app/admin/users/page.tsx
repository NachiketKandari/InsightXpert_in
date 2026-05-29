"use client";

// Users admin tab: table + invite + row actions. Mutations use optimistic
// updates; 409 "last_admin" responses from the backend surface as a toast.

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirm } from "@/components/ui/confirm-dialog";
import {
  useAdminUsers,
  useDeleteUser,
  useInviteUser,
  usePatchUser,
  useResetPassword,
  type AdminUser,
} from "@/hooks/use-admin-users";

function formatLastSeen(ts: number | null): string {
  if (!ts) return "Never";
  return new Date(ts * 1000).toLocaleString();
}

function handleMutationError(err: unknown, fallback: string) {
  const msg = err instanceof Error ? err.message : "";
  if (msg === "last_admin") {
    toast.error("Cannot remove or demote the last admin.");
  } else if (msg === "email_exists") {
    toast.error("An account with this email already exists.");
  } else if (msg === "not_found") {
    toast.error("User not found.");
  } else {
    toast.error(fallback);
  }
}

export default function UsersPage() {
  const { data, isLoading, error } = useAdminUsers();
  const invite = useInviteUser();
  const patch = usePatchUser();
  const resetPw = useResetPassword();
  const del = useDeleteUser();
  const { confirm, ConfirmDialog } = useConfirm();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "user">("user");
  const [credential, setCredential] = useState<{
    email: string;
    password: string;
    kind: "invite" | "reset";
  } | null>(null);

  const users = useMemo(() => data ?? [], [data]);

  async function submitInvite() {
    const email = inviteEmail.trim();
    if (!email) return;
    try {
      const result = await invite.mutateAsync({ email, role: inviteRole });
      setInviteOpen(false);
      setInviteEmail("");
      setInviteRole("user");
      setCredential({
        email: result.email,
        password: result.temp_password,
        kind: "invite",
      });
    } catch (err) {
      handleMutationError(err, "Failed to invite user.");
    }
  }

  async function changeRole(u: AdminUser, role: "admin" | "user") {
    if (u.role === role) return;
    try {
      await patch.mutateAsync({ id: u.id, role });
      toast.success(`Role updated for ${u.email}.`);
    } catch (err) {
      handleMutationError(err, "Failed to update role.");
    }
  }

  async function toggleActive(u: AdminUser) {
    try {
      await patch.mutateAsync({ id: u.id, is_active: !u.is_active });
      toast.success(`${u.email} is now ${!u.is_active ? "active" : "inactive"}.`);
    } catch (err) {
      handleMutationError(err, "Failed to update active status.");
    }
  }

  async function doResetPassword(u: AdminUser) {
    const ok = await confirm({
      title: "Reset password",
      description: `Generate a new temporary password for ${u.email}? The old password will stop working immediately.`,
      confirmLabel: "Reset",
    });
    if (!ok) return;
    try {
      const { temp_password } = await resetPw.mutateAsync({ id: u.id });
      setCredential({ email: u.email, password: temp_password, kind: "reset" });
    } catch (err) {
      handleMutationError(err, "Failed to reset password.");
    }
  }

  async function doDelete(u: AdminUser) {
    const ok = await confirm({
      title: "Delete user",
      description: `Delete ${u.email}? This cannot be undone.`,
      confirmLabel: "Delete",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await del.mutateAsync({ id: u.id });
      toast.success(`${u.email} deleted.`);
    } catch (err) {
      handleMutationError(err, "Failed to delete user.");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Users</h2>
          <p className="text-sm text-muted-foreground">
            Invite teammates, rotate passwords, and control access.
          </p>
        </div>
        <Button onClick={() => setInviteOpen(true)}>
          <Plus className="size-4 mr-1" />
          Invite user
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card overflow-x-auto">
        <div className="grid grid-cols-[1.5fr_0.8fr_0.6fr_1fr_auto] min-w-[700px] gap-3 border-b border-border px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <div>Email</div>
          <div>Role</div>
          <div>Active</div>
          <div>Last seen</div>
          <div className="text-right">Actions</div>
        </div>
        {isLoading && (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary" />
          </div>
        )}
        {error && (
          <div className="px-4 py-6 text-sm text-destructive">
            Failed to load users.
          </div>
        )}
        {!isLoading && users.length === 0 && !error && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            No users yet. Invite one to get started.
          </div>
        )}
        {users.map((u) => (
          <div
            key={u.id}
            className="grid grid-cols-[1.5fr_0.8fr_0.6fr_1fr_auto] min-w-[700px] items-center gap-3 border-b border-border/50 px-4 py-2 text-sm last:border-b-0"
          >
            <div className="truncate">
              <span className="font-medium">{u.email}</span>
              {u.must_change_password && (
                <span className="ml-2 rounded bg-yellow-100 px-1.5 py-0.5 text-[10px] font-medium text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
                  Must change pwd
                </span>
              )}
            </div>
            <div>
              <Select
                value={u.role}
                onValueChange={(v) => changeRole(u, v as "admin" | "user")}
              >
                <SelectTrigger className="h-8 w-28 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">user</SelectItem>
                  <SelectItem value="admin">admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <button
                type="button"
                onClick={() => toggleActive(u)}
                className={`inline-flex h-6 items-center rounded-full px-2 text-xs font-medium transition-colors ${
                  u.is_active
                    ? "bg-green-100 text-green-800 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400"
                    : "bg-red-100 text-red-800 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400"
                }`}
              >
                {u.is_active ? "active" : "inactive"}
              </button>
            </div>
            <div className="text-xs text-muted-foreground">
              {formatLastSeen(u.last_seen_at)}
            </div>
            <div className="flex items-center justify-end gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => doResetPassword(u)}
                title="Reset password"
              >
                <KeyRound className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => doDelete(u)}
                className="text-destructive hover:text-destructive"
                title="Delete user"
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Invite dialog */}
      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite user</DialogTitle>
            <DialogDescription>
              We&apos;ll generate a temporary password shown once on the next screen.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                placeholder="teammate@company.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="invite-role">Role</Label>
              <Select
                value={inviteRole}
                onValueChange={(v) => setInviteRole(v as "admin" | "user")}
              >
                <SelectTrigger id="invite-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">user</SelectItem>
                  <SelectItem value="admin">admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInviteOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={submitInvite}
              disabled={invite.isPending || !inviteEmail.trim()}
            >
              {invite.isPending ? "Inviting..." : "Invite"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Credential modal (temp password shown once) */}
      <Dialog
        open={credential !== null}
        onOpenChange={(open) => {
          if (!open) setCredential(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {credential?.kind === "invite"
                ? "User invited"
                : "Password reset"}
            </DialogTitle>
            <DialogDescription>
              This temporary password is shown once. Copy it now — we can&apos;t
              retrieve it later.
            </DialogDescription>
          </DialogHeader>
          {credential && (
            <div className="space-y-3">
              <div className="space-y-1">
                <Label>Email</Label>
                <div className="rounded-md border border-border bg-muted px-3 py-2 text-sm">
                  {credential.email}
                </div>
              </div>
              <div className="space-y-1">
                <Label>Temporary password</Label>
                <div className="flex items-center gap-2">
                  <code className="flex-1 rounded-md border border-border bg-muted px-3 py-2 font-mono text-sm break-all">
                    {credential.password}
                  </code>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      navigator.clipboard.writeText(credential.password);
                      toast.success("Copied to clipboard");
                    }}
                  >
                    <Copy className="size-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setCredential(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog />
    </div>
  );
}
