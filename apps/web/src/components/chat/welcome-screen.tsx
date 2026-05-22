"use client";

import { useRef, useState, useCallback, useEffect, useMemo, startTransition, type KeyboardEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Shuffle, Sparkles } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Textarea } from "@/components/ui/textarea";
import { DatabasePickerPanel } from "@/components/dataset/database-picker-panel";
import { InputToolbar } from "./input-toolbar";
import { GenerationProgress } from "@/components/sample-questions/generation-progress";
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
  const selectedDbId = useChatStore((s) => s.selectedDbId);
  const { data: sampleData, profileQuery } = useSampleQuestions(selectedDbId ?? undefined);
  const { data: databases = [] } = useDatabases();
  const queryClient = useQueryClient();

  // Poll for sample-question generation progress while "pending".
  const { data: sqStatus } = useSampleQuestionStatus(selectedDbId ?? undefined);
  const generateSq = useGenerateSampleQuestions(selectedDbId ?? undefined);

  const sqStatusPending = sqStatus?.status === "pending" || generateSq.isPending;
  const showGenerateButton =
    profileQuery.isSuccess &&
    !sqStatusPending &&
    (sampleData === undefined ||
     sampleData === null ||
     (sampleData && sampleData.status === "failed"));
  const showProgressBar = sqStatusPending || sampleData?.status === "pending";

  // Pre-fetch profiles for ALL databases in parallel as soon as the list
  // arrives, so sample questions are already cached when the user switches
  // databases. TanStack Query deduplicates: if the selected DB's profile is
  // already in-flight from useSampleQuestions, prefetchQuery reuses the same
  // promise instead of firing a duplicate request.
  useEffect(() => {
    if (databases.length === 0) return;
    for (const db of databases) {
      queryClient.prefetchQuery({
        queryKey: ["profile", db.db_id],
        queryFn: () => fetchProfile(db.db_id),
        staleTime: 30_000,
      });
    }
  }, [databases, queryClient]);

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
    } else if (!profileQuery.isFetching) {
      // Profile settled — either succeeded with no sample questions or
      // errored (404 = no profile). Clear stale chips.
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
  }, [allQuestions, profileQuery.isFetching]);

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
          AI-powered analytics for Indian digital payments
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
            placeholder="Ask about Indian digital payments..."
            className="min-h-[36px] max-h-[140px] flex-1 resize-none border-0 bg-transparent px-1 py-1.5 text-sm shadow-none focus-visible:ring-0"
            rows={1}
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
    </div>
  );
}
