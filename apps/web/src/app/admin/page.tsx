"use client";

// Redirect /admin → /admin/overview on the client.
//
// Was previously a Server Component calling `redirect("/admin/overview")`.
// With the client-rendered AdminLayout above it, the server-side redirect is
// streamed as a NEXT_REDIRECT error inside the RSC payload. The client
// resolves it by re-rendering the parent layout with new children while
// effects in AdminGuard (notably `fetchConfig()`) are still settling — the
// hook call sequence observed on the first mount differed from the second,
// producing "Rendered more hooks than during the previous render" on the
// first click to /admin. A client-side redirect avoids the RSC-redirect
// handshake entirely: the layout mounts once, normally, and we navigate.
//
// Note: because `/admin/overview` is the only admin landing, we could
// alternatively make `/admin` itself render the overview tab directly and
// drop the redirect; kept as a redirect so deep links and the sidebar link
// continue to land on a stable canonical URL.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AdminIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/overview");
  }, [router]);
  return null;
}
