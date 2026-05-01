"use client";

import React, { useState, useMemo, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  expandCombinedFootnoteMarkers,
  parseFootnoteRowMap,
  stripRowsDirectives,
} from "@/lib/footnote-parser";
import { useChatStore } from "@/stores/chat-store";

interface AnswerChunkProps {
  content: string;
  /**
   * The id of the assistant message this answer belongs to. Used to scope
   * footnote-citation highlights so the data-table chunk for the same message
   * (and only that message) flashes the cited rows. Optional for back-compat
   * with older callers, but every in-thread render path passes it.
   */
  messageId?: string;
}

/** Extract a footnote id from a remark-gfm footnote anchor href. */
function footnoteIdFromHref(href: string | undefined): string | null {
  if (!href) return null;
  // remark-gfm emits anchors like:
  //   #user-content-fn-1            (footnote definition target)
  //   #user-content-fnref-1         (back-ref from definition)
  //   #user-content-fnref-1-2       (multi-ref disambiguation suffix)
  const m = href.match(/^#user-content-fn(?:ref)?-([^-\s]+)/);
  return m ? m[1] : null;
}

/** Normalize dashes (em-dash, en-dash, hyphen) to spaces and collapse whitespace. */
function normalizeTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[\u2014\u2013\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// Sections always shown expanded
const PRIMARY_SECTIONS = ["direct answer", "supporting evidence"];

// Sections rendered as collapsible dropdowns
const SECONDARY_SECTIONS = [
  "data provenance",
  "business recommendations",
  "caveats",
  "follow up suggestions",
];

interface ParsedSection {
  title: string;
  content: string;
  isPrimary: boolean;
}

/**
 * Split analyst markdown into named sections based on header patterns.
 * Mirrors the parseSections logic from insight-chunk.tsx.
 */
function parseSections(markdown: string): {
  preamble: string;
  sections: ParsedSection[];
} {
  const headerRe =
    /^(?:#{1,3}\s+(?:\d+\.\s*)?(.+)|(?:\d+\.\s*)?\*\*(.+?)\*\*\s*(?:[-—:].*)?)\s*$/gm;

  const matches: { title: string; index: number }[] = [];
  let m: RegExpExecArray | null;

  while ((m = headerRe.exec(markdown)) !== null) {
    const raw = (m[1] || m[2] || "").trim();
    const title = raw
      .replace(/^\d+\.\s*/, "")
      .replace(/[-—:]+$/, "")
      .trim();
    matches.push({ title, index: m.index });
  }

  if (matches.length === 0) {
    return { preamble: markdown, sections: [] };
  }

  const preamble = markdown.slice(0, matches[0].index).trim();
  const sections: ParsedSection[] = [];
  const allKnown = [...PRIMARY_SECTIONS, ...SECONDARY_SECTIONS];

  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index;
    const end =
      i + 1 < matches.length ? matches[i + 1].index : markdown.length;
    const sectionText = markdown.slice(start, end);

    const firstNewline = sectionText.indexOf("\n");
    const body =
      firstNewline >= 0 ? sectionText.slice(firstNewline + 1).trim() : "";

    const normalized = normalizeTitle(matches[i].title);
    const isPrimary = PRIMARY_SECTIONS.some((s) => normalized.includes(s));
    const isKnown = allKnown.some((s) => normalized.includes(s));

    // Unknown sections shown expanded (safe default)
    sections.push({
      title: matches[i].title,
      content: body,
      isPrimary: isPrimary || !isKnown,
    });
  }

  return { preamble, sections };
}

/** Shared markdown renderer for analyst sections. */
function AnalystMarkdown({
  content,
  onFootnoteClick,
}: {
  content: string;
  onFootnoteClick?: (footnoteId: string) => void;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => (
          <h1 className="text-lg font-bold text-foreground mt-4 mb-2">
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-base font-semibold text-foreground mt-3 mb-2">
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-sm font-semibold text-foreground mt-2 mb-1">
            {children}
          </h3>
        ),
        p: ({ children }) => (
          <p className="text-sm text-foreground/90 leading-relaxed mb-2">
            {children}
          </p>
        ),
        ul: ({ children }) => (
          <ul className="text-sm text-foreground/90 list-disc list-inside space-y-1 mb-2">
            {children}
          </ul>
        ),
        ol: ({ children }) => (
          <ol className="text-sm text-foreground/90 list-decimal list-inside space-y-1 mb-2">
            {children}
          </ol>
        ),
        li: ({ children }) => (
          <li className="leading-relaxed">{children}</li>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold text-foreground">{children}</strong>
        ),
        code: ({ children, className }) => {
          const isInline = !className;
          if (isInline) {
            return (
              <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono text-primary">
                {children}
              </code>
            );
          }
          return (
            <code className="block bg-muted p-3 rounded-lg text-xs font-mono overflow-x-auto my-2">
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="bg-muted rounded-lg overflow-x-auto my-2">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div className="overflow-x-auto my-2 rounded-lg border border-border">
            <table className="w-full text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-muted/50">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-1.5 text-xs font-mono border-t border-border">
            {children}
          </td>
        ),
        a: ({ children, href }) => {
          const footnoteId = footnoteIdFromHref(href);
          if (footnoteId !== null) {
            // remark-gfm wraps footnote markers in <sup><a>...</a></sup>.
            // Intercept the click so we can flash the cited rows in the
            // data-table above instead of jumping to the page anchor.
            const isBackref = href?.includes("user-content-fnref-");
            return (
              <a
                href={href}
                data-footnote-id={footnoteId}
                onClick={(e) => {
                  if (onFootnoteClick) {
                    e.preventDefault();
                    onFootnoteClick(footnoteId);
                  }
                }}
                className={
                  isBackref
                    ? "text-primary/70 hover:text-primary underline-offset-2 no-underline"
                    : "text-primary font-medium hover:text-primary/80 underline-offset-2 hover:underline cursor-pointer"
                }
              >
                {children}
              </a>
            );
          }
          return (
            <a
              href={href}
              className="text-primary underline underline-offset-2 hover:text-primary/80"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          );
        },
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-primary/50 pl-3 text-sm text-muted-foreground italic my-2">
            {children}
          </blockquote>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

/** Collapsible section for secondary analyst content. */
function CollapsibleSection({
  title,
  content,
  onFootnoteClick,
}: {
  title: string;
  content: string;
  onFootnoteClick?: (footnoteId: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-left text-sm transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800/50 dark:hover:bg-zinc-800">
        {isOpen ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
        )}
        <span className="font-medium text-zinc-700 dark:text-zinc-300 text-sm">
          {title}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 pt-2 pb-1">
          <AnalystMarkdown content={content} onFootnoteClick={onFootnoteClick} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function AnswerChunkInner({ content, messageId }: AnswerChunkProps) {
  // Parse the {rows=...} footnote directives BEFORE we strip them, so we can
  // wire each [^N] click to the right rows in the data-table above. Then
  // strip the directives from the markdown source so they don't render as
  // visible noise inside the References section.
  const { footnoteRows, displayContent } = useMemo(() => {
    const rows = parseFootnoteRowMap(content);
    // Defense in depth: expand combined inline footnote markers (e.g.
    // `[^3, 5, 6]`) into adjacent single-id markers (`[^3][^5][^6]`) BEFORE
    // stripping `{rows=...}` directives, so the prompt's references survive
    // intact even when the LLM emits an invalid combined form.
    const expanded = expandCombinedFootnoteMarkers(content);
    const stripped = stripRowsDirectives(expanded);
    return { footnoteRows: rows, displayContent: stripped };
  }, [content]);

  const setMessageHighlight = useChatStore((s) => s.setMessageHighlight);

  const handleFootnoteClick = useCallback(
    (footnoteId: string) => {
      if (!messageId) return;
      const rowIndices = footnoteRows[footnoteId] ?? [];
      if (rowIndices.length === 0) return;
      setMessageHighlight({ messageId, rowIndices });
    },
    [messageId, footnoteRows, setMessageHighlight],
  );

  const { preamble, sections } = useMemo(
    () => parseSections(displayContent),
    [displayContent],
  );
  const primarySections = sections.filter((s) => s.isPrimary);
  const secondarySections = sections.filter((s) => !s.isPrimary);
  const hasSections = sections.length > 0;

  return (
    <div className="prose-invert prose-sm max-w-none">
      {hasSections ? (
        <div className="space-y-3">
          {preamble && (
            <AnalystMarkdown
              content={preamble}
              onFootnoteClick={handleFootnoteClick}
            />
          )}

          {primarySections.map((section, i) => (
            <div key={`primary-${i}`}>
              <h3 className="text-sm font-semibold text-foreground mt-2 mb-1.5">
                {section.title}
              </h3>
              <AnalystMarkdown
                content={section.content}
                onFootnoteClick={handleFootnoteClick}
              />
            </div>
          ))}

          {secondarySections.length > 0 && (
            <div className="space-y-2 mt-2">
              {secondarySections.map((section, i) => (
                <CollapsibleSection
                  key={`secondary-${i}`}
                  title={section.title}
                  content={section.content}
                  onFootnoteClick={handleFootnoteClick}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <AnalystMarkdown
          content={displayContent}
          onFootnoteClick={handleFootnoteClick}
        />
      )}
    </div>
  );
}

// Memoized to prevent React-Markdown re-parsing on every parent re-render
// when the content string hasn't changed (e.g. sibling chunks updating).
export const AnswerChunk = React.memo(AnswerChunkInner);
