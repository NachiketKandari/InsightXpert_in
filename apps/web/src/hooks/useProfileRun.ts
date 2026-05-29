// Profiling run state machine.
//
// Wraps `startProfileStream` with the cost-gate handshake + step accounting.
// Consumers (`/databases/[id]/page.tsx`) render directly off `state`.
//
// Transitions:
//
//   idle ──start(flags)──▶ connecting
//                             │
//                             ├── cost_estimate    ──▶ awaiting_confirmation
//                             │                            │
//                             │                            ├── confirmCost ──▶ running
//                             │                            └── cancel      ──▶ idle
//                             │
//                             └── stage_started  ──▶ running(steps[])
//                                     │
//                                     ├── stage_started      → steps[i].state=running
//                                     ├── stage_completed    → steps[i].state=done|skipped
//                                     ├── profile_progress   → steps[i].batch_k/N
//                                     ├── profile_done       → succeeded
//                                     └── profile_error      → failed

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { startProfileStream } from "@/lib/databases/profile-stream";
import {
  PROFILE_STAGE_ORDER,
  type ProfileCostEstimatePayload,
  type ProfileDonePayload,
  type ProfileFlags,
  type ProfileStage,
} from "@/types/database";

export type ProfileStepState =
  | "pending"
  | "running"
  | "done"
  | "skipped"
  | "error";

export interface ProfileStep {
  stage: ProfileStage;
  state: ProfileStepState;
  durationMs: number | null;
  batchIndex: number | null;
  batchTotal: number | null;
  note: string | null;
}

export type ProfileRunState =
  | { kind: "idle" }
  | { kind: "connecting" }
  | {
      kind: "awaiting_confirmation";
      estimate: ProfileCostEstimatePayload;
      pendingFlags: ProfileFlags;
    }
  | { kind: "running"; steps: ProfileStep[]; requestedFlags: ProfileFlags }
  | {
      kind: "succeeded";
      steps: ProfileStep[];
      summary: ProfileDonePayload;
      autoDisabled: boolean;
    }
  | {
      kind: "failed";
      steps: ProfileStep[];
      message: string;
    };

const anyExpensive = (f: ProfileFlags): boolean =>
  f.with_summaries || f.with_quirks || f.with_lsh || f.with_vectors || f.with_table_descriptions;

function seedSteps(): ProfileStep[] {
  return PROFILE_STAGE_ORDER.map((stage) => ({
    stage,
    state: "pending",
    durationMs: null,
    batchIndex: null,
    batchTotal: null,
    note: null,
  }));
}

function flagForStage(flags: ProfileFlags, stage: ProfileStage): boolean {
  switch (stage) {
    case "summaries":
      return flags.with_summaries;
    case "quirks":
      return flags.with_quirks;
    case "lsh":
      return flags.with_lsh;
    case "vectors":
      return flags.with_vectors;
    case "table_descriptions":
      return flags.with_table_descriptions;
    case "schema":
    case "stats":
    case "join_graph":
      return true; // always runs
  }
}

export interface UseProfileRun {
  state: ProfileRunState;
  start: (flags: ProfileFlags) => void;
  /** Confirm a pending cost estimate and launch the real run. */
  confirmCost: () => void;
  /** Cancel an in-flight run or dismiss a pending estimate. */
  cancel: () => void;
  /** Reset to idle. Used after success/error to re-arm the panel. */
  reset: () => void;
}

export function useProfileRun(dbId: string): UseProfileRun {
  const [state, setState] = useState<ProfileRunState>({ kind: "idle" });
  const controllerRef = useRef<AbortController | null>(null);
  // Need access to current state inside stream callbacks without
  // re-subscribing — keep a mutable mirror.
  const stateRef = useRef<ProfileRunState>(state);
  stateRef.current = state;
  // Generation counter — incremented on each runStream call so stale
  // onClose callbacks from a cost-gate stream don't clobber the state
  // after the confirmed stream has already started (race: cost-gate
  // onClose fires after confirmCost → runStream → setState(connecting)).
  const genRef = useRef(0);

  // Abort on unmount so we don't leak a long-running stream.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const runStream = useCallback(
    (flags: ProfileFlags, confirmed: boolean) => {
      // Fresh stream — kill any previous.
      controllerRef.current?.abort();

      const gen = ++genRef.current;
      setState({ kind: "connecting" });

      controllerRef.current = startProfileStream(
        dbId,
        { ...flags, confirmed },
        {
          onChunk: (chunk) => {
            // Silently drop chunks from a previous (cost-gate) stream.
            if (genRef.current !== gen) return;
            setState((prev) => {
              // Terminal states ignore late chunks — don't regress.
              if (prev.kind === "succeeded" || prev.kind === "failed") {
                return prev;
              }
              // Malformed chunks from the server (missing payload) — skip silently.
              if (!chunk.payload) return prev;
              // Ensure we have a `running` baseline the moment the first
              // stage_started arrives.
              const ensureRunning = (): ProfileStep[] => {
                if (prev.kind === "running") return prev.steps;
                return seedSteps();
              };

              switch (chunk.type) {
                case "profile_cost_estimate": {
                  return {
                    kind: "awaiting_confirmation",
                    estimate: chunk.payload,
                    pendingFlags: flags,
                  };
                }
                case "profile_stage_started": {
                  const steps = ensureRunning().map((s) =>
                    s.stage === chunk.payload.stage
                      ? { ...s, state: "running" as ProfileStepState }
                      : s,
                  );
                  return { kind: "running", steps, requestedFlags: flags };
                }
                case "profile_stage_completed": {
                  const note = chunk.payload.note;
                  const nextState: ProfileStepState =
                    note === "skipped"
                      ? "skipped"
                      : note?.startsWith("failed:")
                        ? "error"
                        : "done";
                  const steps = ensureRunning().map((s) =>
                    s.stage === chunk.payload.stage
                      ? {
                          ...s,
                          state: nextState,
                          durationMs: chunk.payload.duration_ms,
                          note,
                        }
                      : s,
                  );
                  return { kind: "running", steps, requestedFlags: flags };
                }
                case "profile_progress": {
                  const steps = ensureRunning().map((s) =>
                    s.stage === chunk.payload.stage
                      ? {
                          ...s,
                          batchIndex: chunk.payload.batch_index,
                          batchTotal: chunk.payload.batch_total,
                        }
                      : s,
                  );
                  return { kind: "running", steps, requestedFlags: flags };
                }
                case "profile_done": {
                  const steps = ensureRunning();
                  // Auto-disable detection: user asked for a stage but it
                  // came back "skipped". (Schema+stats always run, so ignore.)
                  const autoDisabled = steps.some(
                    (s) =>
                      (s.stage === "summaries" ||
                        s.stage === "quirks" ||
                        s.stage === "lsh" ||
                        s.stage === "vectors" ||
                        s.stage === "table_descriptions") &&
                      flagForStage(flags, s.stage) &&
                      s.state === "skipped",
                  );
                  return {
                    kind: "succeeded",
                    steps,
                    summary: chunk.payload,
                    autoDisabled,
                  };
                }
                case "profile_error": {
                  const steps = ensureRunning().map((s) =>
                    s.state === "running"
                      ? { ...s, state: "error" as ProfileStepState }
                      : s,
                  );
                  return {
                    kind: "failed",
                    steps,
                    message: chunk.payload.message,
                  };
                }
              }
            });
          },
          onClose: () => {
            // Stale onClose from a cost-gate stream that finished after
            // the confirmed stream already started (generation changed).
            if (genRef.current !== gen) return;
            // If we're still connecting/running and haven't hit a terminal
            // chunk, treat as a benign close EXCEPT when we're awaiting
            // confirmation (cost-gate path closes the stream intentionally).
            setState((prev) => {
              if (prev.kind === "awaiting_confirmation") return prev;
              if (prev.kind === "succeeded" || prev.kind === "failed") {
                return prev;
              }
              if (prev.kind === "running") {
                return {
                  kind: "failed",
                  steps: prev.steps,
                  message: "connection closed before completion",
                };
              }
              if (prev.kind === "connecting") {
                return {
                  kind: "failed",
                  steps: seedSteps(),
                  message: "connection closed before completion",
                };
              }
              return prev;
            });
          },
          onNetworkError: (err) => {
            if (genRef.current !== gen) return;
            setState((prev) => ({
              kind: "failed",
              steps: prev.kind === "running" ? prev.steps : seedSteps(),
              message: err.message || "network error",
            }));
          },
        },
      );
    },
    [dbId],
  );

  const start = useCallback(
    (flags: ProfileFlags) => {
      // Cheap path (no expensive flags) can skip the cost gate by
      // confirming up-front.
      runStream(flags, !anyExpensive(flags));
    },
    [runStream],
  );

  const confirmCost = useCallback(() => {
    const current = stateRef.current;
    if (current.kind !== "awaiting_confirmation") return;
    runStream(current.pendingFlags, true);
  }, [runStream]);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState({ kind: "idle" });
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setState({ kind: "idle" });
  }, []);

  return { state, start, confirmCost, cancel, reset };
}
