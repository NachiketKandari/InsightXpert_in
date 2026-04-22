"use client";

import { NotificationList } from "@/components/notifications/notification-list";

// Notifications lives under /admin/*, so the sticky header and PageContainer
// come from apps/web/src/app/admin/layout.tsx. We intentionally do NOT wrap
// again here — the 2026-04-24 layout-rhythm audit flagged a double-sticky-
// header / double-wrapper issue previously.

export default function NotificationsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Notifications</h2>
        <p className="text-sm text-muted-foreground">
          Recent in-app events for your account.
        </p>
      </div>
      <NotificationList />
    </div>
  );
}
