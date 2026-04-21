// Centralized feature-flag check for Automations (Phase C1).
// `NEXT_PUBLIC_AUTOMATIONS_ENABLED=true` enables the feature.
// Evaluated at module scope so Next inlines the build-time value.

export const AUTOMATIONS_ENABLED =
  process.env.NEXT_PUBLIC_AUTOMATIONS_ENABLED === "true";
