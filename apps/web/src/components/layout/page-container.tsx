"use client";

// PageContainer — standard page wrapper enforcing consistent max-width,
// horizontal padding, and vertical rhythm across non-chat pages.
// Per 2026-04-24 layout-rhythm audit: `mx-auto max-w-6xl px-4 sm:px-6 py-8 pb-16`.
// Pages that already compose their own wrapper (e.g. chat's app-shell) should
// NOT use this — it is for `/admin/*`, `/databases`, `/automations`, etc.

import { cn } from "@/lib/utils";

export interface PageContainerProps {
  children: React.ReactNode;
  /** Extra classes merged with defaults (not replacing). */
  className?: string;
  /** Override the semantic tag. Defaults to <div>. */
  as?: "div" | "main" | "section";
}

export function PageContainer({
  children,
  className,
  as: Tag = "div",
}: PageContainerProps) {
  return (
    <Tag
      className={cn(
        "mx-auto max-w-6xl px-4 sm:px-6 py-8 pb-16",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
