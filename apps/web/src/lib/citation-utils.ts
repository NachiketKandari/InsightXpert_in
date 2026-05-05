/**
 * Utilities for pre-processing LLM text before markdown rendering:
 *  - Strip ANSI escape sequences (bold, color, etc.) leaked by some models.
 *  - Convert [[N]] bracket citations into remark-gfm-compatible [^N] footnotes
 *    so they render as clickable superscripts instead of raw literal text.
 *  - Repair dangling [^N] inline markers that lack corresponding [^N]:
 *    definitions (the LLM sometimes emits inline markers without definitions,
 *    which remark-gfm renders as literal text).
 */

const ANSI_ESCAPE_RE = /\x1b\[[0-9;]*[a-zA-Z]/g;

export function stripAnsiEscapes(text: string): string {
  return text.replace(ANSI_ESCAPE_RE, "");
}

const BRACKET_CITATION_RE = /\[\[(\d+)\]\]/g;

export interface BracketCitationMapEntry {
  sourceIndex: number;
}

/**
 * Convert [[N]] bracket citations into [^src-N] footnote markers.
 *
 * Each unique source index gets a footnote definition appended at the bottom
 * so remark-gfm renders the inline marker as a clickable superscript.
 *
 * The returned map keys are the footnote IDs (e.g. "src-1") for callers
 * that may want to wire them to enrichment traces or data rows later.
 */
export function convertBracketCitationsToFootnotes(text: string): {
  processed: string;
  footnoteMap: Record<string, BracketCitationMapEntry>;
} {
  const footnoteMap: Record<string, BracketCitationMapEntry> = {};

  let processed = text.replace(
    BRACKET_CITATION_RE,
    (_match, digits: string) => {
      const n = parseInt(digits, 10);
      if (!Number.isFinite(n)) return _match;
      const footnoteId = `src-${n}`;
      if (!footnoteMap[footnoteId]) {
        footnoteMap[footnoteId] = { sourceIndex: n };
      }
      return `[^${footnoteId}]`;
    },
  );

  const definitions = Object.keys(footnoteMap)
    .sort()
    .map((id) => `[^${id}]: Source ${footnoteMap[id].sourceIndex}\n`)
    .join("");

  if (definitions) {
    processed = processed.trimEnd() + "\n\n" + definitions;
  }

  return { processed, footnoteMap };
}

const INLINE_FOOTNOTE_RE = /\[\^([^\]]+)\]/g;
const FOOTNOTE_DEFINITION_RE = /^\[\^([^\]]+)\]:/gm;

/**
 * Detect inline [^N] footnote markers that have no corresponding [^N]:
 * definition and append synthetic definitions so remark-gfm renders them
 * as clickable superscripts instead of literal text.
 *
 * The LLM sometimes emits [^1] markers in the body but fails to produce
 * the mandatory [^1]: definition in the References section. When this
 * happens, remark-gfm treats the dangling reference as plain text.
 */
export function fixDanglingFootnotes(text: string): string {
  // Collect inline references
  const inlineIds = new Set<string>();
  let m: RegExpExecArray | null;

  const clone = new RegExp(INLINE_FOOTNOTE_RE.source, "g");
  while ((m = clone.exec(text)) !== null) {
    inlineIds.add(m[1]);
  }

  if (inlineIds.size === 0) return text;

  // Collect definitions that already exist
  const definedIds = new Set<string>();
  const defRe = new RegExp(FOOTNOTE_DEFINITION_RE.source, "gm");
  while ((m = defRe.exec(text)) !== null) {
    definedIds.add(m[1]);
  }

  // Build synthetic definitions for dangling inline refs
  const missing = [...inlineIds]
    .filter((id) => !definedIds.has(id))
    .sort((a, b) => {
      const na = parseInt(a, 10);
      const nb = parseInt(b, 10);
      if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
      return a.localeCompare(b);
    });

  if (missing.length === 0) return text;

  const synthDefs = missing.map((id) => `[^${id}]: Source row ${id}\n`).join("");
  return text.trimEnd() + "\n\n" + synthDefs;
}
