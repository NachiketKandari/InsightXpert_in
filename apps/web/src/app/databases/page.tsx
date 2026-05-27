"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { DatabaseCard } from "@/components/databases/database-card";
import { useDatabases } from "@/hooks/use-databases";

export default function DatabasesPage() {
  const { data: items, isLoading, isError } = useDatabases();

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 glass border-b border-border px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center gap-3">
          <Link href="/">
            <Button variant="ghost" size="icon" className="size-9">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <h1 className="text-lg font-semibold">Databases</h1>
        </div>
      </header>

      <PageContainer as="main">
        <div className="space-y-4">
          {isLoading ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : isError ? (
            <div className="text-sm text-red-600 dark:text-red-400">
              Failed to load databases.
            </div>
          ) : !items || items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center">
              <p className="text-sm font-medium">No databases yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Upload a CSV or Excel file from the chat sidebar to get started.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((item) => (
                <DatabaseCard key={item.db_id} item={item} />
              ))}
            </div>
          )}
        </div>
      </PageContainer>
    </div>
  );
}
