"use client";

// Visibility controller. A popover with radio-style buttons for Private /
// Shared / Public. When "Shared" is selected, a user-picker appears backed
// by the admin users list. Consumed by the Databases tab today and will be
// reused by the dataset selector later.

import { useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAdminUsers, type AdminUser } from "@/hooks/use-admin-users";
import { cn } from "@/lib/utils";
import type { Visibility } from "@/hooks/use-admin-databases";

export interface VisibilityMenuProps {
  value: Visibility;
  sharedWith?: string[];
  onSubmit: (next: Visibility, sharedWith?: string[]) => void | Promise<void>;
  label?: string;
  disabled?: boolean;
}

function visibilityBadgeClass(v: Visibility): string {
  switch (v) {
    case "public":
      return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300";
    case "shared":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300";
    default:
      return "bg-muted text-foreground";
  }
}

export function VisibilityBadge({ value }: { value: Visibility }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-full px-2 text-xs font-medium capitalize",
        visibilityBadgeClass(value),
      )}
    >
      {value}
    </span>
  );
}

export function VisibilityMenu({
  value,
  sharedWith = [],
  onSubmit,
  label = "Change visibility",
  disabled,
}: VisibilityMenuProps) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<Visibility>(value);
  const [picks, setPicks] = useState<string[]>(sharedWith);
  const [search, setSearch] = useState("");
  const { data: users } = useAdminUsers();

  function openDialog() {
    setChoice(value);
    setPicks(sharedWith);
    setSearch("");
    setOpen(true);
  }

  async function submit() {
    if (choice === "shared") {
      await onSubmit("shared", picks);
    } else {
      await onSubmit(choice, undefined);
    }
    setOpen(false);
  }

  const filteredUsers: AdminUser[] =
    users?.filter((u) =>
      u.email.toLowerCase().includes(search.toLowerCase()),
    ) ?? [];

  function togglePick(id: string) {
    setPicks((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : [...p, id],
    );
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={openDialog}
        disabled={disabled}
        className="h-7 gap-1"
      >
        <VisibilityBadge value={value} />
        <ChevronDown className="size-3" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              {(["private", "shared", "public"] as Visibility[]).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setChoice(v)}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm capitalize transition-colors",
                    choice === v
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-muted/50",
                  )}
                >
                  {v}
                </button>
              ))}
            </div>

            {choice === "shared" && (
              <div className="space-y-2">
                <Label className="text-xs">Share with users</Label>
                <Input
                  placeholder="Search by email"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                {picks.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {picks.map((id) => {
                      const u = users?.find((x) => x.id === id);
                      return (
                        <span
                          key={id}
                          className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs"
                        >
                          {u?.email ?? id}
                          <button
                            type="button"
                            onClick={() => togglePick(id)}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            <X className="size-3" />
                          </button>
                        </span>
                      );
                    })}
                  </div>
                )}
                <div className="max-h-48 overflow-y-auto rounded-md border border-border">
                  {filteredUsers.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-muted-foreground">
                      No users match.
                    </div>
                  ) : (
                    filteredUsers.map((u) => {
                      const checked = picks.includes(u.id);
                      return (
                        <button
                          key={u.id}
                          type="button"
                          onClick={() => togglePick(u.id)}
                          className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-muted/50"
                        >
                          <span className="truncate">{u.email}</span>
                          {checked && <Check className="size-4 text-primary" />}
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            )}

            {choice === "public" && (
              <p className="text-xs text-muted-foreground">
                Anyone signed in will see this database.
              </p>
            )}
            {choice === "private" && (
              <p className="text-xs text-muted-foreground">
                Only the owner (and admins) can see this database.
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={submit}
              disabled={choice === "shared" && picks.length === 0}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
