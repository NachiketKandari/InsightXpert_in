// apps/web/src/proxy.ts
// Renamed from middleware.ts per Next 16 deprecation
// (https://nextjs.org/docs/messages/middleware-to-proxy). Next 16 requires the
// exported function to be named `proxy` (or be the default export) to match
// the new file convention.
//
// Redirects unauth requests to /login?next=...; skips static files, the auth
// pages themselves, and API routes. Identity check is "is the session cookie
// present" — we don't re-verify the signature here (let the API do that).

import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/register", "/change-password"];
const SESSION_COOKIE = process.env.NEXT_PUBLIC_SESSION_COOKIE_NAME || "ix_session";

function isPublic(pathname: string): boolean {
  if (PUBLIC_PATHS.includes(pathname)) return true;
  if (pathname.startsWith("/share/")) return true;
  if (pathname.startsWith("/_next/")) return true;
  if (pathname.startsWith("/api/")) return true;
  if (pathname === "/favicon.ico") return true;
  if (pathname.match(/\.[^/]+$/)) return true;
  return false;
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (isPublic(pathname)) return NextResponse.next();

  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", pathname + search);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!api/|_next/|.*\\..*).*)"],
};
