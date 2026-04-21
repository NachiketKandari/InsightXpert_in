// Notifications store (Phase C1).
// Mirrors the chat-store pattern: hydrated via a REST poll, live-updated via
// the SSE stream from `@/lib/automations/sse`. Components mount
// `useNotificationsStream` once (gated on feature flag + auth) and push new
// events into the store via `ingestStreamed`.

import { create } from "zustand";
import {
  fetchAllNotifications,
  fetchNotifications,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/automations/api";
import type { Notification } from "@/types/automation";

interface NotificationState {
  notifications: Notification[];
  allNotifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  isLoadingAll: boolean;

  fetchNotifications: (unreadOnly?: boolean) => Promise<void>;
  fetchAllNotifications: (unreadOnly?: boolean) => Promise<void>;
  fetchUnreadCount: () => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  /** Push a freshly-streamed notification event (from the SSE hook). */
  ingestStreamed: (n: Notification) => void;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  allNotifications: [],
  unreadCount: 0,
  isLoading: false,
  isLoadingAll: false,

  fetchNotifications: async (unreadOnly = false) => {
    set({ isLoading: true });
    const data = await fetchNotifications(unreadOnly);
    set({ notifications: data ?? [], isLoading: false });
  },

  fetchAllNotifications: async (unreadOnly = false) => {
    set({ isLoadingAll: true });
    const data = await fetchAllNotifications(unreadOnly);
    set({ allNotifications: data ?? [], isLoadingAll: false });
  },

  fetchUnreadCount: async () => {
    const data = await fetchUnreadCount();
    if (data) set({ unreadCount: data.count });
  },

  markAsRead: async (id) => {
    // Optimistic update — dismiss immediately
    const prev = get();
    set((s) => ({
      notifications: s.notifications.map((n) =>
        n.id === id ? { ...n, is_read: true } : n,
      ),
      allNotifications: s.allNotifications.map((n) =>
        n.id === id ? { ...n, is_read: true } : n,
      ),
      unreadCount: Math.max(0, s.unreadCount - 1),
    }));
    const ok = await markNotificationRead(id);
    if (!ok) {
      set({
        notifications: prev.notifications,
        allNotifications: prev.allNotifications,
        unreadCount: prev.unreadCount,
      });
    }
  },

  markAllAsRead: async () => {
    const prev = get();
    set((s) => {
      const ownIds = new Set(s.notifications.map((n) => n.id));
      return {
        notifications: s.notifications.map((n) => ({ ...n, is_read: true })),
        allNotifications: s.allNotifications.map((n) =>
          ownIds.has(n.id) ? { ...n, is_read: true } : n,
        ),
        unreadCount: 0,
      };
    });
    const ok = await markAllNotificationsRead();
    if (!ok) {
      set({
        notifications: prev.notifications,
        allNotifications: prev.allNotifications,
        unreadCount: prev.unreadCount,
      });
    }
  },

  ingestStreamed: (n) => {
    set((s) => {
      // Dedupe on id — SSE backlog can re-emit on reconnect.
      if (s.notifications.some((x) => x.id === n.id)) return s;
      const unread = n.is_read ? s.unreadCount : s.unreadCount + 1;
      return {
        notifications: [n, ...s.notifications],
        unreadCount: unread,
      };
    });
  },
}));
