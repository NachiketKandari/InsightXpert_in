// POST-backed SSE consumer for `/api/v1/databases/{db_id}/profile`.
//
// Mirrors the pattern in `lib/sse-client.ts:createSSEStream` — we use
// fetch() + ReadableStream instead of EventSource because we need to POST a
// JSON body (stage flags + confirmed). Each line of the response is either:
//   - `data: <json-envelope>` where envelope = {type, payload}
//   - `data: [DONE]` sentinel
//   - comment or blank (ignored)
//
// The stream ends for three reasons:
//   1. Cost-gate: server emits `profile_cost_estimate` and closes.
//   2. Successful run: `profile_done` + `[DONE]`.
//   3. Error: `profile_error` + `[DONE]`, OR the network / abort.

import { SSE_BASE_URL } from "@/lib/constants";
import type {
  ProfileChunk,
  ProfileRunRequest,
} from "@/types/database";

export interface ProfileStreamCallbacks {
  /** Called for every parsed chunk. */
  onChunk: (chunk: ProfileChunk) => void;
  /** Stream ended cleanly (either [DONE] or server closed). */
  onClose: () => void;
  /** Network-level or parse-level failure (NOT a server-emitted profile_error). */
  onNetworkError: (err: Error) => void;
}

/**
 * Kick off a profiling run. Returns an AbortController so the caller
 * (typically the page unmount) can cancel in flight.
 */
export function startProfileStream(
  dbId: string,
  body: ProfileRunRequest,
  callbacks: ProfileStreamCallbacks,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(
        `${SSE_BASE_URL}/api/v1/databases/${encodeURIComponent(dbId)}/profile`,
        {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        },
      );

      if (!res.ok) {
        if (res.status === 401 && typeof window !== "undefined") {
          // Mirror `lib/api.ts:handleUnauthorized` for SSE since we bypass apiFetch.
          const onAuthPage =
            window.location.pathname === "/login" ||
            window.location.pathname === "/change-password";
          if (!onAuthPage) {
            const next = encodeURIComponent(
              window.location.pathname + window.location.search,
            );
            window.location.replace(`/login?next=${next}`);
            return;
          }
        }
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        // Last element may be a partial line — keep it in the buffer.
        buffer = lines.pop() ?? "";

        for (const raw of lines) {
          const line = raw.trim();
          if (!line || line.startsWith(":")) continue;

          if (line.startsWith("data:")) {
            const data = line.slice(5).trimStart();
            if (data === "[DONE]") {
              callbacks.onClose();
              return;
            }
            try {
              const parsed = JSON.parse(data);
              if (parsed && typeof parsed === "object" && "type" in parsed) {
                // Server sends `data` for the payload field (ChatChunk envelope);
                // normalize to the `payload` key the state machine expects.
                const chunk = {
                  type: parsed.type,
                  payload: parsed.data ?? parsed.payload,
                } as ProfileChunk;
                callbacks.onChunk(chunk);
              }
            } catch {
              // Drop malformed frames rather than tearing down the stream —
              // the server contract guarantees JSON but we don't want a bad
              // byte to kill the user's run.
            }
          }
        }
      }

      // Reader finished without a [DONE] sentinel — still a clean close.
      callbacks.onClose();
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // Caller-initiated cancellation — silent.
        return;
      }
      callbacks.onNetworkError(err as Error);
    }
  })();

  return controller;
}
