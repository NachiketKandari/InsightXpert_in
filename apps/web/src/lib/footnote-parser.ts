/**
 * Parser for the `{rows=...}` directive emitted by the answer_synthesizer.j2
 * prompt's References section. The directive is a literal token attached to
 * each footnote definition; the FE strips it from displayed text and uses the
 * resolved row indices to wire clickable in-answer citations to the source
 * rows in the data-table chunk above the answer.
 *
 * Supported syntaxes inside the braces:
 *   {rows=N}          single 1-based row index
 *   {rows=N,M,P}      comma-separated list
 *   {rows=N-M}        inclusive range
 *   {rows=1,3-5,8}    combinations
 *
 * All indices in the input are 1-based (matching how the LLM thinks about
 * rows). The parser returns 0-based indices ready to use with array access.
 */

/** Expand a `{rows=...}` body into 0-based row indices. */
export function parseRowsSpec(spec: string): number[] {
  const trimmed = spec.trim();
  if (!trimmed) return [];

  const out: number[] = [];
  for (const part of trimmed.split(",")) {
    const piece = part.trim();
    if (!piece) continue;
    const rangeMatch = piece.match(/^(\d+)\s*-\s*(\d+)$/);
    if (rangeMatch) {
      const start = parseInt(rangeMatch[1], 10);
      const end = parseInt(rangeMatch[2], 10);
      if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
      const lo = Math.min(start, end);
      const hi = Math.max(start, end);
      for (let n = lo; n <= hi; n++) {
        if (n >= 1) out.push(n - 1);
      }
      continue;
    }
    const single = parseInt(piece, 10);
    if (Number.isFinite(single) && single >= 1) {
      out.push(single - 1);
    }
  }

  // Dedupe + preserve first-occurrence order.
  const seen = new Set<number>();
  const dedup: number[] = [];
  for (const n of out) {
    if (!seen.has(n)) {
      seen.add(n);
      dedup.push(n);
    }
  }
  return dedup;
}

/**
 * Scan markdown for footnote definitions of the form
 *   [^N]: <text> {rows=...}
 * and return a map of footnote id (string) to 0-based row indices.
 *
 * Definitions without a `{rows=...}` suffix yield `[]` (no rows to highlight)
 * but the id still appears in the map so callers can detect the footnote.
 */
export function parseFootnoteRowMap(markdown: string): Record<string, number[]> {
  const map: Record<string, number[]> = {};
  // Match [^id]: ... possibly ending with {rows=...}
  // Multiline-aware; stops at next blank line or next footnote/header.
  const re = /^\[\^([^\]]+)\]:\s*([^\n]*)$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(markdown)) !== null) {
    const id = m[1];
    const body = m[2];
    const rowsMatch = body.match(/\{rows=([^}]*)\}/);
    map[id] = rowsMatch ? parseRowsSpec(rowsMatch[1]) : [];
  }
  return map;
}

/** Strip `{rows=...}` directives from markdown so they don't render visibly. */
export function stripRowsDirectives(markdown: string): string {
  return markdown.replace(/\s*\{rows=[^}]*\}/g, "");
}

/**
 * Defense-in-depth pre-parser. Models occasionally collapse multiple footnote
 * citations into a single bracket — `[^3, 5, 6]`, `[^3,5,6]`, `[^3-6]` — which
 * react-markdown / remark-gfm cannot parse (it only understands single-id
 * markers like `[^3]`). The unparsed form leaks through as broken literal text.
 *
 * This helper rewrites combined inline markers into adjacent single-id markers
 * (e.g. `[^3][^5][^6]`) before handing the markdown to ReactMarkdown so the
 * existing footnote-id click handlers wire up normally.
 *
 * Definition lines (`[^3]: ...`) are left untouched — those have a colon
 * immediately after the closing bracket and must not be split.
 *
 * Supported combined forms:
 *   [^3, 5, 6]   →  [^3][^5][^6]
 *   [^3,5,6]     →  [^3][^5][^6]
 *   [^3-6]       →  [^3][^4][^5][^6]
 *   [^3, 5-7]    →  [^3][^5][^6][^7]
 *
 * Plain `[^3]` markers and definition lines are returned unchanged.
 */
export function expandCombinedFootnoteMarkers(markdown: string): string {
  // Match `[^...]` NOT immediately followed by `:` (which would mean a
  // definition line). Capture the body between the brackets so we can decide
  // whether it needs expansion.
  return markdown.replace(/\[\^([^\]]+)\](?!:)/g, (match, body: string) => {
    // Single integer id — leave alone (the common case).
    if (/^\s*\d+\s*$/.test(body)) return match;

    // Only attempt to expand if the body looks like a numeric list/range:
    // digits, commas, dashes, and whitespace only. Anything else (e.g. named
    // footnotes like `[^note-1]`) is left untouched.
    if (!/^[\s\d,\-]+$/.test(body)) return match;

    const ids: number[] = [];
    for (const part of body.split(",")) {
      const piece = part.trim();
      if (!piece) continue;
      const rangeMatch = piece.match(/^(\d+)\s*-\s*(\d+)$/);
      if (rangeMatch) {
        const start = parseInt(rangeMatch[1], 10);
        const end = parseInt(rangeMatch[2], 10);
        if (!Number.isFinite(start) || !Number.isFinite(end)) return match;
        const lo = Math.min(start, end);
        const hi = Math.max(start, end);
        for (let n = lo; n <= hi; n++) ids.push(n);
        continue;
      }
      const single = parseInt(piece, 10);
      if (!Number.isFinite(single)) return match;
      ids.push(single);
    }

    if (ids.length === 0) return match;

    // Dedupe preserving first-occurrence order so `[^3, 3, 5]` → `[^3][^5]`.
    const seen = new Set<number>();
    const out: string[] = [];
    for (const id of ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(`[^${id}]`);
    }
    return out.join("");
  });
}
