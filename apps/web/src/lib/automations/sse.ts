// Notifications SSE hook (Phase C1).
// Subscribes to GET /api/v1/notifications/stream; delivers each event payload
// to a callback. The component that mounts this hook owns the routing — e.g.
// the notifications store on auth-bootstrap, plus the header bell on hydration.
//
// Uses `fetch`-based streaming over `EventSource` so cookies travel with the
// request (EventSource doesn't honor credentials cross-origin).
// If `NEXT_PUBLIC_API_URL` is set we stream straight to that host (matches the
// existing chat SSE pattern in `@/lib/sse-client`).

"use client";

import { useEffect, useRef } from "react";
import { SSE_BASE_URL } from "@/lib/constants";
import type { Notification } from "@/types/automation";

export interface NotificationStreamCallbacks {
  onNotification: (n: Notification) => void;
  onError?: (err: Error) => void;
  onOpen?: () => void;
}

interface Options {
  /** When false, the hook is inert (no connection). Gated by feature flag. */
  enabled?: boolean;
}

const DONE_MARKER = "[DONE]";
const MAX_BACKOFF_MS = 30_000;

/**
 * Subscribe to /api/v1/notifications/stream. Reconnects with exponential
 * backoff on network error. Returns nothing; consumers mount and unmount.
 */
export function useNotificationsStream(
  callbacks: NotificationStreamCallbacks,
  options: Options = {},
): void {
  const { enabled = true } = options;
  // Stable ref for callbacks so we don't tear the stream down on every render.
  const cbRef = useRef(callbacks);
  useEffect(() => {
    cbRef.current = callbacks;
  }, [callbacks]);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let backoff = 1_000;
    let controller: AbortController | null = null;

    async function runOnce() {
      controller = new AbortController();
      try {
        const res = await fetch(`${SSE_BASE_URL}/api/v1/notifications/stream`, {
          credentials: "include",
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!res.ok || !res.body) {
          throw new Error(`SSE connect failed: ${res.status}`);
        }
        cbRef.current.onOpen?.();
        backoff = 1_000; // reset on successful connect

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by double-newlines.
          let frameEnd: number;
          while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, frameEnd);
            buffer = buffer.slice(frameEnd + 2);
            const dataLine = frame
              .split("\n")
              .find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            const data = dataLine.slice(5).trim();
            if (!data || data === DONE_MARKER) continue;
            try {
              const parsed = JSON.parse(data) as Notification;
              cbRef.current.onNotification(parsed);
            } catch {
              // Malformed frame — skip
            }
          }
        }
      } catch (err) {
        if (cancelled) return;
        cbRef.current.onError?.(err as Error);
      } finally {
        controller = null;
      }
    }

    async function loop() {
      while (!cancelled) {
        await runOnce();
        if (cancelled) break;
        // Backoff before reconnect
        await new Promise((r) => setTimeout(r, backoff));
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      }
    }

    loop();

    return () => {
      cancelled = true;
      controller?.abort();
    };
  }, [enabled]);
}
