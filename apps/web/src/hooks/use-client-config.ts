import { useClientConfigStore } from "@/stores/client-config-store";

export function useClientConfig() {
  const config = useClientConfigStore((s) => s.config);
  const isLoading = useClientConfigStore((s) => s.isLoading);
  const fetchConfig = useClientConfigStore((s) => s.fetchConfig);

  const isFeatureEnabled = (feature: string): boolean => {
    // No config means show everything (default)
    if (!config) return true;
    return (config.features as unknown as Record<string, boolean>)[feature] ?? true;
  };

  return { config, isLoading, fetchConfig, isFeatureEnabled };
}
