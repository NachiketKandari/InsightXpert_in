"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AppLogo } from "@/components/ui/app-logo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { changePassword } from "@/lib/auth-api";

// Next 16: `useSearchParams()` bails out of CSR static generation unless the
// consumer is wrapped in a Suspense boundary — wrap at the route level.
export default function ChangePasswordPage() {
  return (
    <Suspense fallback={null}>
      <ChangePasswordForm />
    </Suspense>
  );
}

function ChangePasswordForm() {
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
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm glass border-border">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl flex items-center justify-center gap-2">
            <AppLogo className="size-8" />
            <span>
              Insight<span className="text-primary dark:text-cyan-accent">Xpert</span>
            </span>
          </CardTitle>
          <CardDescription>
            Set a new password for your account. Minimum 12 characters.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
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
            <div className="flex flex-col gap-2">
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
            <div className="flex flex-col gap-2">
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
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Saving…" : "Save"}
            </Button>
            {error ? (
              <p className="text-sm text-center text-destructive">{error}</p>
            ) : null}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
