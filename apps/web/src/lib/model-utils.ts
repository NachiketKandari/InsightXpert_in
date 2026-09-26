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

/** Display name for a model id: "gemini-2.5-flash" -> "2.5 Flash".
 * OpenRouter-style ids ("org/model:variant") render without the vendor
 * prefix or variant suffix: "nvidia/nemotron-3-ultra:free" -> "Nemotron 3 Ultra".
 */
export function formatModelName(model: string, provider: string): string {
  let name = model;
  let freeTier = false;
  // Strip OpenRouter vendor prefix ("org/") and variant suffix (":free").
  if (name.includes("/")) {
    name = name.slice(name.lastIndexOf("/") + 1);
  }
  if (name.includes(":")) {
    freeTier = name.slice(name.indexOf(":") + 1).toLowerCase() === "free";
    name = name.slice(0, name.indexOf(":"));
  }
  // Strip provider prefix (e.g. "gemini-", "ollama/")
  const prefixes = [provider + "-", provider + "/"];
  for (const p of prefixes) {
    if (name.toLowerCase().startsWith(p)) {
      name = name.slice(p.length);
      break;
    }
  }
  // Replace hyphens/underscores with spaces and title-case each word
  const pretty = name
    .replace(/[-_]/g, " ")
    .replace(/\b[a-z]/g, (c) => c.toUpperCase());
  return freeTier ? `${pretty} (Free)` : pretty;
}
