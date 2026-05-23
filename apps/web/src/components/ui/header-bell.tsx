"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface HeaderBellProps {
  icon: React.ReactNode;
  count: number;
  badgeClassName?: string;
  label: string;
  pollIntervalMs: number;
  onPoll: () => void;
  onOpen: () => void;
  onHover?: () => void;
  /** Delay the initial poll by this many ms. Subsequent interval polls are unaffected. */
  deferMs?: number;
  renderPopover: (controls: { showAll: () => void }) => React.ReactNode;
  renderModal: (open: boolean, onOpenChange: (open: boolean) => void) => React.ReactNode;
}

export function HeaderBell({
  icon,
  count,
  badgeClassName = "bg-destructive",
  label,
  pollIntervalMs,
  onPoll,
  onOpen,
  onHover,
  deferMs,
  renderPopover,
  renderModal,
}: HeaderBellProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Prefetch data on hover so it is ready before the user clicks.
  // Debounced 150ms to avoid redundant fetches during rapid mouse movement.
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    return () => clearTimeout(hoverTimerRef.current);
  }, []);
  const handleHover = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
    }
    hoverTimerRef.current = setTimeout(() => {
      onHover?.();
    }, 150);
  }, [onHover]);

  // Poll on interval, paused when the tab is in the background.
  // When deferMs is set, the initial poll is delayed to avoid competing
  // with critical data fetches during initial page load.
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | undefined;

    const startPolling = () => {
      onPoll();
      interval = setInterval(onPoll, pollIntervalMs);
    };

    if (deferMs && deferMs > 0) {
      const initialTimer = setTimeout(startPolling, deferMs);
      const handleVisibilityDeferred = () => {
        if (document.hidden) {
          clearTimeout(initialTimer);
          if (interval) clearInterval(interval);
        } else {
          startPolling();
        }
      };
      document.addEventListener("visibilitychange", handleVisibilityDeferred);
      return () => {
        clearTimeout(initialTimer);
        if (interval) clearInterval(interval);
        document.removeEventListener("visibilitychange", handleVisibilityDeferred);
      };
    }

    startPolling();
    const handleVisibility = () => {
      if (document.hidden) {
        if (interval) clearInterval(interval);
      } else {
        onPoll();
        interval = setInterval(onPoll, pollIntervalMs);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      if (interval) clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [onPoll, pollIntervalMs, deferMs]);

  // Toggle popover; fetch data when opening
  const handleToggle = useCallback(() => {
    setPopoverOpen((prev) => {
      if (!prev) onOpen();
      return !prev;
    });
  }, [onOpen]);

  // Close popover on outside click
  useEffect(() => {
    if (!popoverOpen) return;
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setPopoverOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [popoverOpen]);

  // Transition from popover → modal
  const showAll = useCallback(() => {
    setPopoverOpen(false);
    setModalOpen(true);
  }, []);

  return (
    <>
      <div className="relative" ref={popoverRef}>
        <Button
          variant="ghost"
          size="icon"
          className="size-9 relative"
          onClick={handleToggle}
          onMouseEnter={handleHover}
          aria-label={label}
        >
          {icon}
          {count > 0 && (
            <span
              className={cn(
                "absolute -top-0.5 -right-0.5 flex items-center justify-center size-4 rounded-full text-[10px] font-medium text-white",
                badgeClassName,
              )}
            >
              {count > 9 ? "9+" : count}
            </span>
          )}
        </Button>

        {popoverOpen && (
          <div className="absolute right-0 top-full mt-1 z-50">
            {renderPopover({ showAll })}
          </div>
        )}
      </div>

      {renderModal(modalOpen, setModalOpen)}
    </>
  );
}
