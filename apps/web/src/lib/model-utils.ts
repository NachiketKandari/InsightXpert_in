export const PROVIDER_LABELS: Record<string, string> = {
  gemini: "Gemini",
  deepseek: "DeepSeek",
  openrouter: "OpenRouter",
  ollama: "Ollama",
  vertex_ai: "Vertex AI",
};

/** Label for any provider served by the backend — known brands use the map
 * above, anything new (e.g. future gateways) auto-generates Title Case so
 * the FE never needs a redeploy for a BE-added provider. */
export function providerLabel(provider: string): string {
  const known = PROVIDER_LABELS[provider];
  if (known) return known;
  return provider
    .replace(/[-_]/g, " ")
    .replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

/** Strip provider prefix and title-case: "gemini-2.5-flash" -> "2.5 Flash" */
export function formatModelName(model: string, provider: string): string {
  let name = model;
  // Strip provider prefix (e.g. "gemini-", "ollama/")
  const prefixes = [provider + "-", provider + "/"];
  for (const p of prefixes) {
    if (name.toLowerCase().startsWith(p)) {
      name = name.slice(p.length);
      break;
    }
  }
  // Replace hyphens/underscores with spaces and title-case each word
  return name
    .replace(/[-_]/g, " ")
    .replace(/\b[a-z]/g, (c) => c.toUpperCase());
}
