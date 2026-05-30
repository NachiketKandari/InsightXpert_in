"use client";

// Admin shell: auth/admin gate + sticky header + horizontal tab bar.
// All 8 admin pages render as children beneath this layout.

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { useCurrentUser } from "@/hooks/use-current-user";
import { cn } from "@/lib/utils";
import { AUTOMATIONS_ENABLED } from "@/lib/automations/feature-flag";

const TABS: { href: string; label: string }[] = [
  { href: "/admin/overview", label: "Overview" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/metrics", label: "Query Metrics" },
  { href: "/admin/audit", label: "Audit Log" },
  { href: "/admin/databases", label: "Databases" },
  { href: "/admin/conversations", label: "Conversations" },
  { href: "/admin/prompts", label: "Prompts" },
  { href: "/admin/rag", label: "RAG" },
  // Phase C1: Automations tab appears only when the flag is on.
  ...(AUTOMATIONS_ENABLED
    ? [{ href: "/admin/automations", label: "Automations" }]
    : []),
];

function AdminGuard({ children }: { children: React.ReactNode }) {
  const { isAdmin, isLoading } = useCurrentUser();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAdmin) {
      router.push("/");
    }
  }, [isLoading, isAdmin, router]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (!isAdmin) return null;
  return <>{children}</>;
}

function AdminTabs() {
  const pathname = usePathname() ?? "";
  return (
    <nav className="overflow-x-auto border-b border-border">
      <ul className="mx-auto flex max-w-6xl min-w-max items-center gap-1 px-6 sm:px-8 lg:px-10">
        {TABS.map((t) => {
          const active = pathname.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                className={cn(
                  "inline-block whitespace-nowrap px-4 py-3.5 text-sm font-medium transition-colors",
                  "border-b-2 -mb-px",
                  active
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <AdminGuard>
        <div className="min-h-screen bg-background">
          <header className="sticky top-0 z-20 glass border-b border-border">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3 sm:px-8 lg:px-10">
              <div className="flex items-center gap-3">
                <Link href="/">
                  <Button variant="ghost" size="icon" className="size-9">
                    <ArrowLeft className="size-4" />
                  </Button>
                </Link>
                <h1 className="text-lg font-semibold">Admin</h1>
              </div>
            </div>
            <AdminTabs />
          </header>
          <PageContainer as="main">{children}</PageContainer>
        </div>
      </AdminGuard>
    </AuthGuard>
  );
}
