"use client";

import { useCallback } from "react";
import { Bell } from "lucide-react";
import { useNotificationStore } from "@/stores/notification-store";
import { HeaderBell } from "@/components/ui/header-bell";
import { NotificationPopover } from "./notification-popover";
import { NotificationAllModal } from "./notification-all-modal";
import { useNotificationsStream } from "@/lib/automations/sse";
import { AUTOMATIONS_ENABLED } from "@/lib/automations/feature-flag";

export function NotificationBell() {
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const fetchUnreadCount = useNotificationStore((s) => s.fetchUnreadCount);
  const fetchNotifications = useNotificationStore((s) => s.fetchNotifications);
  const ingestStreamed = useNotificationStore((s) => s.ingestStreamed);

  // Phase C1: subscribe to the live notifications SSE stream. Gated on the
  // feature flag — when disabled the hook is inert (no network).
  useNotificationsStream(
    { onNotification: ingestStreamed },
    { enabled: AUTOMATIONS_ENABLED },
  );

  const handleOpen = useCallback(() => fetchNotifications(true), [fetchNotifications]);
  const handleHover = useCallback(() => fetchNotifications(true), [fetchNotifications]);

  return (
    <HeaderBell
      icon={<Bell className="size-4.5" />}
      count={unreadCount}
      badgeClassName="bg-destructive"
      label="Notifications"
      pollIntervalMs={30_000}
      onPoll={fetchUnreadCount}
      onOpen={handleOpen}
      onHover={handleHover}
      renderPopover={({ showAll }) => (
        <NotificationPopover onShowAll={showAll} />
      )}
      renderModal={(open, onOpenChange) => (
        <NotificationAllModal open={open} onOpenChange={onOpenChange} />
      )}
    />
  );
}
