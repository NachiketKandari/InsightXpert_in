"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Step {
  title: string;
  description: string;
}

const STEPS: Step[] = [
  {
    title: "Upload your data",
    description:
      "Start by uploading a CSV or Excel file. It will be converted into a queryable database automatically.",
  },
  {
    title: "Ask a question",
    description:
      "Type your question in natural language. InsightXpert translates it to SQL and shows you the results.",
  },
  {
    title: "Explore results",
    description:
      "Review the generated SQL, explore charts, and use sample questions to dive deeper into your data.",
  },
];

const STORAGE_KEY = "insightxpert_onboarding_seen";

function hasLocalCompleted(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function markLocalCompleted(): void {
  try {
    localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // noop
  }
}

export interface OnboardingTourProps {
  /** Whether the user has no databases yet (structural pre-condition). */
  enabled: boolean;
  /** CSS selectors for each step's target element. Index matches STEPS. */
  targetSelectors: string[];
  /** Global admin toggle — if false, tour never shows for anyone. */
  featureEnabled: boolean;
  /** Per-user flag — if true, user has already completed the tour. */
  onboardingCompleted: boolean;
  /** When true, the tour stays hidden until all async preconditions settle. */
  loading?: boolean;
}

export function OnboardingTour({
  enabled,
  targetSelectors,
  featureEnabled,
  onboardingCompleted,
  loading = false,
}: OnboardingTourProps) {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);
  const [tooltipPos, setTooltipPos] = useState<{ top: number; left: number } | null>(null);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [completing, setCompleting] = useState(false);
  const rafRef = useRef<number>(0);

  // Show the tour only if: async preconditions have settled, structural
  // pre-condition (no DBs), admin hasn't killed the feature, and user hasn't
  // already completed it (checked both locally and via server flag).
  const shouldShow = !loading && enabled && featureEnabled && !onboardingCompleted && !hasLocalCompleted();

  // Initialize.
  useEffect(() => {
    if (!shouldShow) return;
    setVisible(true);
    setStep(0);
  }, [shouldShow]);

  // Position the tooltip relative to the current step's target element.
  const updatePosition = useCallback(() => {
    const selector = targetSelectors[step];
    if (!selector) return;
    const el = document.querySelector(selector);
    if (!el) {
      setTooltipPos(null);
      setTargetRect(null);
      return;
    }
    const rect = el.getBoundingClientRect();
    setTargetRect(rect);

    // Position tooltip card below the target, centered horizontally.
    const cardWidth = 340;
    const cardHeight = 160; // approximate
    const gap = 12;
    let left = rect.left + rect.width / 2 - cardWidth / 2;
    let top = rect.bottom + gap;

    // Clamp horizontally.
    if (left < 16) left = 16;
    if (left + cardWidth > window.innerWidth - 16) {
      left = window.innerWidth - cardWidth - 16;
    }

    // If not enough space below, position above.
    if (top + cardHeight > window.innerHeight - 16) {
      top = rect.top - cardHeight - gap;
    }

    // If still not fitting, position at bottom of screen.
    if (top < 16) {
      top = window.innerHeight - cardHeight - 16;
    }

    setTooltipPos({ top, left });
  }, [step, targetSelectors]);

  // Update position on step change and window resize.
  useEffect(() => {
    if (!visible) return;
    updatePosition();
    const onResize = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(updatePosition);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(rafRef.current);
    };
  }, [visible, updatePosition]);

  const dismiss = useCallback(() => {
    setVisible(false);
    markLocalCompleted();
    // Fire-and-forget: persist completion to server.
    setCompleting(true);
    fetch("/api/v1/auth/me/onboarding-complete", { method: "POST", credentials: "include" })
      .catch(() => { /* best-effort */ })
      .finally(() => setCompleting(false));
  }, []);

  const next = useCallback(() => {
    if (step >= STEPS.length - 1) {
      dismiss();
    } else {
      setStep((s) => s + 1);
    }
  }, [step, dismiss]);

  if (!visible || !shouldShow) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <AnimatePresence>
      {/* Backdrop */}
      <motion.div
        key="onboarding-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[60] bg-background/60"
        onClick={dismiss}
      />

      {/* Target highlight ring */}
      {targetRect && (
        <motion.div
          key={`highlight-${step}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2 }}
          className="fixed z-[61] pointer-events-none"
          style={{
            top: targetRect.top - 4,
            left: targetRect.left - 4,
            width: targetRect.width + 8,
            height: targetRect.height + 8,
            borderRadius: 8,
            boxShadow: "0 0 0 4px rgba(6,182,212,0.5), 0 0 20px rgba(6,182,212,0.3)",
          }}
        />
      )}

      {/* Tooltip card */}
      {tooltipPos && (
        <motion.div
          key={`tooltip-${step}`}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed z-[62] w-[340px] rounded-xl border border-border bg-card shadow-xl p-4"
          style={{ top: tooltipPos.top, left: tooltipPos.left }}
        >
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="flex gap-1.5">
                {STEPS.map((_, i) => (
                  <span
                    key={i}
                    className={`block size-1.5 rounded-full transition-colors ${
                      i === step
                        ? "bg-primary dark:bg-cyan-accent"
                        : i < step
                          ? "bg-primary/30"
                          : "bg-border"
                    }`}
                  />
                ))}
              </div>
              <span className="text-[10px] text-muted-foreground">
                {step + 1} of {STEPS.length}
              </span>
            </div>
            <button
              onClick={dismiss}
              className="text-muted-foreground/50 hover:text-muted-foreground transition-colors cursor-pointer"
              aria-label="Skip tour"
            >
              <X className="size-3.5" />
            </button>
          </div>

          <h3 className="text-sm font-semibold mb-1">{current.title}</h3>
          <p className="text-xs text-muted-foreground mb-4 leading-relaxed">
            {current.description}
          </p>

          <div className="flex items-center justify-between gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={dismiss}
              className="text-xs h-7"
            >
              Skip
            </Button>
            <Button
              size="sm"
              onClick={next}
              className="text-xs h-7 gap-1"
            >
              {isLast ? "Got it" : "Next"}
              {!isLast && <ChevronRight className="size-3" />}
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
