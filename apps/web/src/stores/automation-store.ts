// Phase C1 Zustand store for automations CRUD, test-trigger, and templates.
// The workflow-builder (visual canvas) state is deferred to Phase C2 and has
// been removed from this store. Callers that used to `openWorkflowBuilder`
// should navigate to `/automations` instead and use the "New Automation"
// dialog on that page.

import { create } from "zustand";
import { toast } from "sonner";
import {
  createAutomationResult as apiCreateAutomationResult,
  deleteAutomation as apiDeleteAutomation,
  fetchAutomations as apiFetchAutomations,
  fetchRunHistory as apiFetchRunHistory,
  runAutomationNow as apiRunNow,
  toggleAutomation as apiToggleAutomation,
  updateAutomation as apiUpdateAutomation,
  createTriggerTemplate as apiCreateTemplate,
  deleteTriggerTemplate as apiDeleteTemplate,
  fetchTriggerTemplates as apiFetchTemplates,
} from "@/lib/automations/api";
import type {
  Automation,
  AutomationRun,
  CreateAutomationPayload,
  TriggerCondition,
  TriggerTemplate,
} from "@/types/automation";

interface TestTriggerState {
  intervalId: ReturnType<typeof setInterval>;
  intervalSeconds: number;
  iterationCount: number;
  lastResult: { status: string; message: string; run: AutomationRun | null } | null;
  isRunning: boolean;
}

interface AutomationState {
  automations: Automation[];
  isLoading: boolean;
  error: string | null;

  // New-automation dialog state (list-page dialog). Phase C1 replaces the
  // workflow-canvas builder with a simple form-based dialog.
  newAutomationDialogOpen: boolean;

  // Test trigger state
  activeTestTriggers: Record<string, TestTriggerState>;

  // Trigger templates
  triggerTemplates: TriggerTemplate[];
  isLoadingTemplates: boolean;

  // CRUD
  fetchAutomations: () => Promise<void>;
  createAutomation: (payload: CreateAutomationPayload) => Promise<Automation | null>;
  updateAutomation: (id: string, payload: Partial<CreateAutomationPayload>) => Promise<Automation | null>;
  deleteAutomation: (id: string) => Promise<boolean>;
  toggleAutomation: (id: string) => Promise<Automation | null>;
  runNow: (id: string) => Promise<{ status: string; message: string; run: AutomationRun | null } | null>;
  fetchRunHistory: (id: string, limit?: number) => Promise<AutomationRun[]>;

  // Templates
  fetchTriggerTemplates: () => Promise<void>;
  createTriggerTemplate: (name: string, description: string | null, conditions: TriggerCondition[]) => Promise<TriggerTemplate | null>;
  deleteTriggerTemplate: (id: string) => Promise<boolean>;

  // Test trigger
  startTestTrigger: (id: string, intervalSeconds: number) => void;
  stopTestTrigger: (id: string) => void;

  // Dialog
  openNewAutomationDialog: () => void;
  closeNewAutomationDialog: () => void;
}

export const useAutomationStore = create<AutomationState>((set, get) => ({
  automations: [],
  isLoading: false,
  error: null,
  newAutomationDialogOpen: false,
  activeTestTriggers: {},
  triggerTemplates: [],
  isLoadingTemplates: false,

  fetchAutomations: async () => {
    set({ isLoading: true, error: null });
    const data = await apiFetchAutomations();
    set({ automations: data ?? [], isLoading: false });
  },

  createAutomation: async (payload) => {
    const result = await apiCreateAutomationResult(payload);
    if (result.ok) {
      set((s) => ({ automations: [result.data, ...s.automations] }));
      return result.data;
    }
    // Surface specific server messages here so every caller (dialog, deep-link
    // flows, future programmatic creators) gets the right toast without
    // duplicating the status-code mapping.
    if (result.status === 429) {
      toast.error("Automation limit reached", {
        description: result.message,
      });
    } else if (result.status === 400) {
      // 400 carries a server-authored detail — surface verbatim.
      toast.error(result.message);
    } else if (result.status === 0) {
      toast.error("Network error", { description: result.message });
    } else {
      toast.error("Failed to create automation", { description: result.message });
    }
    return null;
  },

  updateAutomation: async (id, payload) => {
    const data = await apiUpdateAutomation(id, payload);
    if (data) {
      set((s) => ({
        automations: s.automations.map((a) => (a.id === id ? data : a)),
      }));
    }
    return data;
  },

  deleteAutomation: async (id) => {
    const ok = await apiDeleteAutomation(id);
    if (ok) {
      set((s) => ({
        automations: s.automations.filter((a) => a.id !== id),
      }));
    }
    return ok;
  },

  toggleAutomation: async (id) => {
    const data = await apiToggleAutomation(id);
    if (data) {
      set((s) => ({
        automations: s.automations.map((a) => (a.id === id ? data : a)),
      }));
    }
    return data;
  },

  runNow: async (id) => {
    return await apiRunNow(id);
  },

  fetchRunHistory: async (id, limit = 20) => {
    return (await apiFetchRunHistory(id, limit)) ?? [];
  },

  fetchTriggerTemplates: async () => {
    set({ isLoadingTemplates: true });
    const data = await apiFetchTemplates();
    set({ triggerTemplates: data ?? [], isLoadingTemplates: false });
  },

  createTriggerTemplate: async (name, description, conditions) => {
    const data = await apiCreateTemplate(name, description, conditions);
    if (data) {
      set((s) => ({ triggerTemplates: [data, ...s.triggerTemplates] }));
    }
    return data;
  },

  deleteTriggerTemplate: async (id) => {
    const ok = await apiDeleteTemplate(id);
    if (ok) {
      set((s) => ({
        triggerTemplates: s.triggerTemplates.filter((t) => t.id !== id),
      }));
    }
    return ok;
  },

  startTestTrigger: (id, intervalSeconds) => {
    const existing = get().activeTestTriggers[id];
    if (existing) clearInterval(existing.intervalId);

    const runOnce = async () => {
      set((s) => ({
        activeTestTriggers: {
          ...s.activeTestTriggers,
          [id]: { ...s.activeTestTriggers[id], isRunning: true },
        },
      }));

      const result = await get().runNow(id);

      set((s) => {
        const current = s.activeTestTriggers[id];
        if (!current) return s;
        return {
          activeTestTriggers: {
            ...s.activeTestTriggers,
            [id]: {
              ...current,
              iterationCount: current.iterationCount + 1,
              lastResult: result,
              isRunning: false,
            },
          },
        };
      });
    };

    runOnce();
    const intervalId = setInterval(runOnce, intervalSeconds * 1000);

    set((s) => ({
      activeTestTriggers: {
        ...s.activeTestTriggers,
        [id]: {
          intervalId,
          intervalSeconds,
          iterationCount: 0,
          lastResult: null,
          isRunning: true,
        },
      },
    }));
  },

  stopTestTrigger: (id) => {
    const existing = get().activeTestTriggers[id];
    if (existing) clearInterval(existing.intervalId);
    set((s) => {
      const next = { ...s.activeTestTriggers };
      delete next[id];
      return { activeTestTriggers: next };
    });
  },

  openNewAutomationDialog: () => set({ newAutomationDialogOpen: true }),
  closeNewAutomationDialog: () => set({ newAutomationDialogOpen: false }),
}));
