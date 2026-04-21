"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { changePassword } from "@/lib/auth-api";

export default function ChangePasswordPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [current, setCurrent] = useState("");
  const [next1, setNext1] = useState("");
  const [next2, setNext2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (next1.length < 12) {
      setError("New password must be at least 12 characters.");
      return;
    }
    if (next1 !== next2) {
      setError("New passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await changePassword(current, next1);
      // change-password invalidates the cookie — force re-login
      router.replace(`/login?next=${encodeURIComponent(next)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Change failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-6 shadow-sm"
      >
        <h1 className="text-xl font-semibold">Change password</h1>
        <p className="text-sm text-muted-foreground">
          Set a new password for your account. Minimum 12 characters.
        </p>
        <div className="space-y-1">
          <Label htmlFor="current">Current password</Label>
          <Input
            id="current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="new1">New password</Label>
          <Input
            id="new1"
            type="password"
            autoComplete="new-password"
            value={next1}
            onChange={(e) => setNext1(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="new2">Confirm new password</Label>
          <Input
            id="new2"
            type="password"
            autoComplete="new-password"
            value={next2}
            onChange={(e) => setNext2(e.target.value)}
            required
          />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? "Saving…" : "Save"}
        </Button>
      </form>
    </div>
  );
}
