import { API_BASE_URL } from "./constants";

export interface ApiFetchOptions extends RequestInit {
  // When true, a 401 response will NOT trigger a browser redirect to /login.
  // Use this for endpoints (e.g. /auth/me) that handle 401 themselves so the
  // redirect doesn't loop when an unauthenticated user visits /login.
  skipAuthRedirect?: boolean;
}

function handleUnauthorized(res: Response): void {
  if (res.status === 401 && typeof window !== "undefined") {
    // Don't redirect if we're already on an auth page — avoids redirect loops.
    const { pathname } = window.location;
    const onAuthPage =
      pathname === "/login" || pathname === "/change-password";
    if (!onAuthPage) {
      const next = encodeURIComponent(
        window.location.pathname + window.location.search,
      );
      window.location.replace(`/login?next=${next}`);
    }
  }
}

export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {}
): Promise<Response> {
  const { skipAuthRedirect, ...rest } = options;
  const isFormData = rest.body instanceof FormData;
  const method = (rest.method || "GET").toUpperCase();
  // Let the browser honour server Cache-Control headers for reads.
  // Writes (POST/PUT/PATCH/DELETE) stay "no-store". Callers can still
  // override via options.cache if needed.
  const cache =
    "cache" in rest
      ? rest.cache
      : method === "GET" || method === "HEAD"
        ? "default"
        : "no-store";
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    credentials: "include",
    cache,
    headers: {
      // Don't set Content-Type for FormData — the browser sets it with the
      // correct multipart boundary automatically.
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...rest.headers,
    },
  });

  if (res.status === 401 && !skipAuthRedirect) {
    handleUnauthorized(res);
  }

  return res;
}

export async function apiCall<T>(path: string, options?: ApiFetchOptions): Promise<T | null> {
  try {
    const res = await apiFetch(path, options);
    if (!res.ok) return null;
    return await res.json() as T;
  } catch {
    return null;
  }
}
