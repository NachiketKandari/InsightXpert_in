import { create } from "zustand";
import { apiFetch, apiCall } from "@/lib/api";
import type { AgentMode, PipelineMode } from "@/lib/sse-client";

interface ProviderModels {
  provider: string;
  models: string[];
}

interface SettingsState {
  currentProvider: string;
  currentModel: string;
  providers: ProviderModels[];
  loading: boolean;
  agentMode: AgentMode;
  /** Tier-1: admin-only pipeline mode override. "auto" = no override. */
  pipelineMode: PipelineMode;

  fetchConfig: () => Promise<void>;
  switchModel: (provider: string, model: string) => Promise<void>;
  setAgentMode: (mode: AgentMode) => void;
  setPipelineMode: (mode: PipelineMode) => void;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  currentProvider: "deepseek",
  currentModel: "deepseek-v4-flash",
  providers: [],
  loading: false,
  // Default to "auto" — the FE pre-routes via POST /api/v1/chat/route.
  // The classifier picks basic vs. agentic per question. Users can override
  // via the dropdown.
  agentMode: "auto" as AgentMode,
  pipelineMode: "auto" as PipelineMode,

  fetchConfig: async () => {
    set({ loading: true });
    const data = await apiCall<{ current_provider: string; current_model: string; providers: ProviderModels[] }>("/api/v1/config");
    if (data) {
      set({
        currentProvider: data.current_provider,
        currentModel: data.current_model,
        providers: data.providers,
      });
    }
    set({ loading: false });
  },

  switchModel: async (provider: string, model: string) => {
    const prev = { provider: get().currentProvider, model: get().currentModel };
    // Optimistic update
    set({ currentProvider: provider, currentModel: model });

    try {
      const res = await apiFetch("/api/v1/config/switch", {
        method: "POST",
        body: JSON.stringify({ provider, model }),
      });
      if (!res.ok) {
        // Revert on failure
        set({ currentProvider: prev.provider, currentModel: prev.model });
      }
    } catch {
      set({ currentProvider: prev.provider, currentModel: prev.model });
    }
  },

  setAgentMode: (mode) => set({ agentMode: mode }),
  setPipelineMode: (mode) => set({ pipelineMode: mode }),
}));
