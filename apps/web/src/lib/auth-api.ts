// apps/web/src/lib/auth-api.ts
// Thin wrapper for auth-related network calls.
// Keeps `fetch` bureaucracy out of the UI components.

import { apiFetch } from "@/lib/api";

export type Role = "admin" | "user";

export interface CurrentUser {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
}

export async function fetchMe(): Promise<CurrentUser | null> {
  const res = await apiFetch("/api/v1/auth/me", { skipAuthRedirect: true });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`GET /auth/me failed: ${res.status}`);
  return res.json();
}

export async function login(
  email: string,
  password: string,
): Promise<CurrentUser> {
  const res = await apiFetch("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Login failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function logout(): Promise<void> {
  await apiFetch("/api/v1/auth/logout", { method: "POST" });
}

export async function register(
  email: string,
  password: string,
): Promise<CurrentUser> {
  const res = await apiFetch("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    if (res.status === 409) throw new Error("An account with this email already exists.");
    if (res.status === 422) throw new Error(detail || "Password must be at least 8 characters.");
    throw new Error(`Registration failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function changePassword(
  current_password: string,
  new_password: string,
): Promise<void> {
  const res = await apiFetch("/api/v1/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Change password failed: ${res.status} ${detail}`);
  }
}
