"use client";

import { useRef, useState, useCallback, useEffect, useMemo, startTransition, type KeyboardEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Shuffle, Sparkles, Upload, CheckCircle2, Loader2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { DatabasePickerPanel } from "@/components/dataset/database-picker-panel";
import { InputToolbar } from "./input-toolbar";
import { GenerationProgress } from "@/components/sample-questions/generation-progress";
import { CsvUploadDialog } from "@/components/dataset/csv-upload-dialog";
import { ProfileStepper } from "@/components/databases/profile-stepper";
import { OnboardingTour } from "@/components/onboarding/onboarding-tour";
import { startProfileStream } from "@/lib/databases/profile-stream";
import { useChatStore } from "@/stores/chat-store";
import { useClientConfigStore } from "@/stores/client-config-store";
import { useVoiceInput } from "@/hooks/use-voice-input";
import { useDatabases } from "@/hooks/use-databases";
import {
  useSampleQuestions,
  useSampleQuestionStatus,
  useGenerateSampleQuestions,
  fetchProfile,
} from "@/hooks/use-sample-questions";
import {
  PROFILE_STAGE_ORDER,
  type ProfileChunk,
  type ProfileFlags,
  type ProfileStage,
  type ProfileDonePayload,
} from "@/types/database";
import type { ProfileStep, ProfileStepState, ProfileRunState } from "@/hooks/useProfileRun";

function pickRandom(pool: string[], count: number, exclude?: string[]): string[] {
  const filtered = exclude ? pool.filter((q) => !exclude.includes(q)) : [...pool];
  const result: string[] = [];
  for (let i = 0; i < count && filtered.length > 0; i++) {
    const idx = Math.floor(Math.random() * filtered.length);
    result.push(filtered[idx]);
    filtered.splice(idx, 1);
  }
  return result;
}

interface WelcomeScreenProps {
  onSendMessage: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
}

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.2 },
  },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" as const } },
};

export function WelcomeScreen({ onSendMessage, onStop, isStreaming }: WelcomeScreenProps) {
  const [value, setValue] = useState("");
  const [questions, setQuestions] = useState<string[]>([]);
  const [shuffleKey, setShuffleKey] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const displayName = useClientConfigStore((s) => s.config?.branding?.display_name);
  const { voiceState, voiceError, toggleVoice, clearVoiceText } = useVoiceInput(setValue);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [onboardingCompleted, setOnboardingCompleted] = useState(true); // default true = don't flash tour
  const [onboardingLoading, setOnboardingLoading] = useState(true); // gate tour until fetch settles
  const configFeatures = useClientConfigStore((s) => s.config?.features);
  const onboardingEnabled = (configFeatures as Record<string, boolean> | undefined)?.["onboarding_enabled"] ?? true;
  const selectedDbId = useChatStore((s) => s.selectedDbId);
  const { data: sampleData, profileQuery, ensure } = useSampleQuestions(selectedDbId ?? undefined);
  const { data: databases = [], isLoading: databasesLoading } = useDatabases();
  const queryClient = useQueryClient();

  // Post-upload profiling flow — inline state machine (no useProfileRun hook,
  // so dbId can be passed directly to startProfileStream without timing issues).
  const [profileState, setProfileState] = useState<ProfileRunState>({ kind: "idle" });
  const profileControllerRef = useRef<AbortController | null>(null);

  // Abort profiling stream on unmount.
  useEffect(() => {
    return () => profileControllerRef.current?.abort();
  }, []);

  const handleProfileRequired = useCallback(
    (dbId: string) => {
      // Cancel any in-flight stream.
      profileControllerRef.current?.abort();

      setProfileState({ kind: "connecting" });

      const flags: ProfileFlags = {
        with_summaries: false,
        with_quirks: false,
        with_lsh: false,
        with_vectors: false,
      };

      profileControllerRef.current = startProfileStream(
        dbId,
        { ...flags, confirmed: true },
        {
          onChunk: (chunk: ProfileChunk) => {
            setProfileState((prev) => {
              if (prev.kind === "succeeded" || prev.kind === "failed") return prev;

              const ensureRunning = (): ProfileStep[] => {
                if (prev.kind === "running") return prev.steps;
                return PROFILE_STAGE_ORDER.map((stage) => ({
                  stage,
                  state: "pending" as ProfileStepState,
                  durationMs: null,
                  batchIndex: null,
                  batchTotal: null,
                  note: null,
                }));
              };

              switch (chunk.type) {
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
                      ? { ...s, state: nextState, durationMs: chunk.payload.duration_ms, note }
                      : s,
                  );
                  return { kind: "running", steps, requestedFlags: flags };
                }
                case "profile_progress": {
                  const steps = ensureRunning().map((s) =>
                    s.stage === chunk.payload.stage
                      ? { ...s, batchIndex: chunk.payload.batch_index, batchTotal: chunk.payload.batch_total }
                      : s,
                  );
                  return { kind: "running", steps, requestedFlags: flags };
                }
                case "profile_done": {
                  const steps = ensureRunning();
                  const summary: ProfileDonePayload = chunk.payload;
                  return { kind: "succeeded", steps, summary, autoDisabled: false };
                }
                case "profile_error": {
                  const steps = ensureRunning().map((s) =>
                    s.state === "running" ? { ...s, state: "error" as ProfileStepState } : s,
                  );
                  return { kind: "failed", steps, message: chunk.payload.message };
                }
                default:
                  return prev;
              }
            });
          },
          onClose: () => {
            setProfileState((prev) => {
              if (prev.kind === "succeeded" || prev.kind === "failed") return prev;
              if (prev.kind === "running") {
                return { kind: "failed", steps: prev.steps, message: "Connection closed before completion." };
              }
              return { kind: "failed", steps: [], message: "Connection closed before completion." };
            });
          },
          onNetworkError: (err: Error) => {
            setProfileState((prev) => ({
              kind: "failed",
              steps: prev.kind === "running" ? prev.steps : [],
              message: err.message || "Network error during profiling.",
            }));
          },
        },
      );
    },
    [],
  );

  // When profiling succeeds, trigger sample question generation.
  useEffect(() => {
    if (profileState.kind === "succeeded") {
      ensure.mutate();
    }
  }, [profileState.kind, ensure]);

  // Clear profiling UI on failure after a short delay.
  useEffect(() => {
    if (profileState.kind === "failed") {
      const timer = setTimeout(() => {
        setProfileState({ kind: "idle" });
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [profileState.kind]);

  const selectedDbName = useMemo(() => {
    if (!selectedDbId) return null;
    return selectedDbId.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }, [selectedDbId]);

  // Does the currently selected DB have a profile at all? Derived from the
  // database list (instant, cached) so we can clear chips immediately when
  // switching to an unprofiled DB instead of waiting for the profile fetch.
  const selectedDbHasProfile = selectedDbId
    ? databases.some((d) => d.db_id === selectedDbId && d.has_profile)
    : false;

  // Poll for sample-question generation progress while "pending".
  const { data: sqStatus } = useSampleQuestionStatus(selectedDbId ?? undefined);
  const generateSq = useGenerateSampleQuestions(selectedDbId ?? undefined);

  const sqStatusPending = sqStatus?.status === "pending" || generateSq.isPending;
  // Profile has "settled" once it's not fetching/loading — this includes both
  // HTTP 200 (profile exists) and HTTP 404 (no profile yet). We need the
  // generate button to appear in both cases, not just on success.
  const profileSettled =
    !profileQuery.isFetching && !profileQuery.isLoading && selectedDbId != null;
  const showGenerateButton =
    profileSettled &&
    !sqStatusPending &&
    (sampleData === undefined ||
     sampleData === null ||
     (sampleData && sampleData.status === "failed"));
  const showProgressBar = sqStatusPending || sampleData?.status === "pending";

  // Pre-fetch the profile ONLY for the currently selected DB so sample
  // questions are already cached when the user starts interacting. Avoids
  // N parallel fetches for every database in the list.
  useEffect(() => {
    if (!selectedDbId) return;
    queryClient.prefetchQuery({
      queryKey: ["profile", selectedDbId],
      queryFn: () => fetchProfile(selectedDbId),
      staleTime: 30_000,
    });
  }, [selectedDbId, queryClient]);

  // Build pool from per-DB sample questions, refreshing when data changes
  const allQuestions = useMemo(
    () => sampleData?.categories?.flatMap((cat) => cat.questions) ?? [],
    [sampleData],
  );

  // Track the last non-empty pool so chips don't blink to empty during a
  // DB switch (while the new profile is in-flight). Clear when the profile
  // query settles with no data so stale chips from the previous DB don't
  // linger on a DB that genuinely has no sample questions.
  const prevQuestionsRef = useRef<string[]>([]);
  useEffect(() => {
    if (allQuestions.length > 0) {
      prevQuestionsRef.current = allQuestions;
    }
  }, [allQuestions]);

  // Re-pick when the question pool changes (new DB, new generation).
  useEffect(() => {
    if (allQuestions.length > 0) {
      startTransition(() => {
        setQuestions(pickRandom(allQuestions, 3));
        setShuffleKey((k) => k + 1);
      });
    } else if (!selectedDbHasProfile) {
      // The target DB has no profile — we know instantly from the cached
      // database list that no questions exist. Clear chips immediately
      // instead of waiting for the 404 from the profile endpoint.
      if (prevQuestionsRef.current.length > 0) {
        prevQuestionsRef.current = [];
      }
      startTransition(() => {
        setQuestions([]);
        setShuffleKey((k) => k + 1);
      });
    } else if (!profileQuery.isFetching) {
      // Profile settled — either succeeded with no sample questions or
      // errored. Clear stale chips.
      if (prevQuestionsRef.current.length > 0) {
        prevQuestionsRef.current = [];
      }
      startTransition(() => {
        setQuestions([]);
        setShuffleKey((k) => k + 1);
      });
    }
    // Else: allQuestions is empty but the profile query is still in flight
    // (DB switch in progress). Keep old chips visible to avoid the blink.
  }, [allQuestions, profileQuery.isFetching, selectedDbHasProfile]);

  // Fetch user's onboarding status from server. Default to true (completed)
  // to avoid flashing the tour on every load before the fetch resolves.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/auth/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { onboarding_completed?: boolean } | null) => {
        if (!cancelled && data) {
          setOnboardingCompleted(data.onboarding_completed ?? true);
        }
      })
      .catch(() => { /* leave as default */ })
      .finally(() => { if (!cancelled) setOnboardingLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Subscribe to pendingInput changes outside the render cycle to avoid
  // cascading setState-in-effect warnings.
  useEffect(() => {
    return useChatStore.subscribe((state) => {
      if (state.pendingInput) {
        setValue(state.pendingInput);
        state.setPendingInput(null);
        textareaRef.current?.focus();
      }
    });
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSendMessage(trimmed);
    setValue("");
    clearVoiceText();
  }, [value, isStreaming, onSendMessage, clearVoiceText]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleShuffle = useCallback(() => {
    setQuestions((prev) => pickRandom(allQuestions, 3, prev));
    setShuffleKey((k) => k + 1);
  }, [allQuestions]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-3 sm:px-4 py-8 sm:py-12">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-6 text-center"
      >
        <h1 className="text-4xl font-bold leading-tight tracking-tight pb-1 sm:text-5xl">
          {displayName || (<>Insight<span className="text-primary dark:text-cyan-accent">Xpert</span></>)}
        </h1>
        <p className="mt-3 text-sm text-muted-foreground sm:text-base">
          {selectedDbName
            ? `AI-powered analytics for ${selectedDbName}`
            : "AI-powered analytics for your data"}
        </p>
      </motion.div>

      {/* Centered input bar */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="w-full max-w-2xl"
      >
        <div className="glass-input flex flex-col rounded-2xl px-3 py-1.5">
          <Textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={selectedDbName
              ? `Ask anything about ${selectedDbName}...`
              : "Select a database to get started..."}
            className="min-h-[36px] max-h-[140px] flex-1 resize-none border-0 bg-transparent px-1 py-1.5 text-sm shadow-none focus-visible:ring-0"
            rows={1}
            data-onboarding-target="chat-input"
          />
          <InputToolbar
            onSend={handleSend}
            onStop={onStop}
            isStreaming={isStreaming}
            canSend={!!value.trim()}
            voiceState={voiceState}
            voiceError={voiceError}
            toggleVoice={toggleVoice}
          />
        </div>
      </motion.div>

      <p className="mt-2 text-center text-[11px] text-muted-foreground/60">
        AI can make mistakes. Please double-check responses.
      </p>

      {/* First-class database picker — shown only on the landing screen so
          users don't have to hunt for the header dropdown. */}
      <DatabasePickerPanel />

      {/* Upload CTA — when no databases exist, give a prominent upload button. */}
      {!databasesLoading && databases.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="mt-4"
        >
          <Button
            onClick={() => setUploadOpen(true)}
            size="lg"
            className="gap-2"
            data-onboarding-target="upload"
          >
            <Upload className="size-4" />
            Upload your data
          </Button>
        </motion.div>
      )}

      {/* Post-upload profiling progress */}
      {profileState.kind === "connecting" && (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Connecting to profiling…
        </div>
      )}
      {profileState.kind === "running" && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 w-full max-w-md"
        >
          <p className="mb-2 text-xs font-medium text-muted-foreground">Profiling your data…</p>
          <ProfileStepper
            steps={profileState.kind === "running" ? profileState.steps : []}
            totalDurationMs={null}
          />
        </motion.div>
      )}
      {profileState.kind === "succeeded" && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400"
        >
          <CheckCircle2 className="size-4" />
          Profiling complete — {profileState.summary.table_count} table
          {profileState.summary.table_count !== 1 ? "s" : ""},{" "}
          {profileState.summary.column_count} column
          {profileState.summary.column_count !== 1 ? "s" : ""}
          {profileState.summary.total_duration_ms != null &&
            ` in ${(profileState.summary.total_duration_ms / 1000).toFixed(1)}s`}
        </motion.div>
      )}
      {profileState.kind === "failed" && (
        <div className="mt-4 text-sm text-destructive">
          Profiling failed: {profileState.message}
        </div>
      )}

      {/* Generate sample questions button — shown when a profiled DB has no
          questions yet and generation is not already in progress. */}
      {showGenerateButton && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4"
        >
          <button
            onClick={() => generateSq.mutate()}
            disabled={generateSq.isPending}
            className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium bg-primary/10 text-primary hover:bg-primary/20 transition-colors cursor-pointer disabled:opacity-50"
          >
            <Sparkles className="size-4" />
            Generate sample questions
          </button>
        </motion.div>
      )}

      {/* Progress bar — shown while generation is in flight. */}
      {showProgressBar && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4"
        >
          <GenerationProgress progress={sqStatus?.progress ?? null} />
        </motion.div>
      )}

      {/* Suggestion chips */}
      <AnimatePresence mode="wait">
        <motion.div
          key={shuffleKey}
          variants={container}
          initial="hidden"
          animate="show"
          exit="hidden"
          className="mt-4 sm:mt-6 grid w-full max-w-2xl grid-cols-1 min-[400px]:grid-cols-3 gap-2 sm:gap-3"
          data-onboarding-target="suggestions"
        >
          {questions.map((question) => (
            <motion.button
              key={question}
              variants={item}
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => onSendMessage(question)}
              className="glass cursor-pointer rounded-xl px-4 py-3 text-left text-xs leading-relaxed text-foreground/80 transition-shadow hover:shadow-[0_0_20px_rgba(6,182,212,0.15)] sm:text-sm flex items-start"
            >
              <span className="line-clamp-3">{question}</span>
            </motion.button>
          ))}
        </motion.div>
      </AnimatePresence>

      {/* Shuffle button */}
      <motion.button
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.5 }}
        onClick={handleShuffle}
        className="mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-muted-foreground/70 transition-colors hover:text-foreground/80 hover:bg-accent/50 cursor-pointer"
      >
        <Shuffle className="size-3" />
        Shuffle suggestions
      </motion.button>

      {allQuestions.length > 3 && (
        <motion.button
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.6 }}
          onClick={() => useChatStore.getState().setSampleQuestionsOpen(true)}
          className="mt-2 text-xs text-primary/70 hover:text-primary transition-colors cursor-pointer"
        >
          View all sample questions →
        </motion.button>
      )}

      <CsvUploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        onUploadSuccess={() => {
          void queryClient.invalidateQueries({ queryKey: ["databases", "list"] });
        }}
        onProfileRequired={handleProfileRequired}
      />

      <OnboardingTour
        enabled={databases.length === 0}
        targetSelectors={[
          '[data-onboarding-target="upload"]',
          '[data-onboarding-target="chat-input"]',
          '[data-onboarding-target="suggestions"]',
        ]}
        featureEnabled={onboardingEnabled}
        onboardingCompleted={onboardingCompleted}
        loading={onboardingLoading || databasesLoading}
      />
    </div>
  );
}
