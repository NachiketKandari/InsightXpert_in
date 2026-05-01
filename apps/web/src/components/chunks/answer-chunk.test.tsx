import { describe, it, expect, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { AnswerChunk } from "./answer-chunk";
import { useChatStore } from "@/stores/chat-store";

describe("AnswerChunk citation footnotes", () => {
  beforeEach(() => {
    useChatStore.setState({ messageHighlight: null });
  });

  it("strips {rows=...} directives from rendered text", () => {
    const md = [
      "## Direct Answer",
      "The schools table has 49 columns[^1].",
      "",
      "[^1]: schools table — 49 metadata columns {rows=1}",
    ].join("\n");
    const { container } = render(
      <AnswerChunk content={md} messageId="msg-1" />,
    );
    expect(container.textContent).not.toContain("{rows=");
    expect(container.textContent).toContain("schools table");
  });

  it("dispatches setMessageHighlight with parsed rows on footnote click", () => {
    const md = [
      "## Direct Answer",
      "Average across rows[^1].",
      "",
      "[^1]: satscores avg {rows=1-3}",
    ].join("\n");
    const { container } = render(
      <AnswerChunk content={md} messageId="msg-42" />,
    );

    // remark-gfm renders the inline footnote marker as <sup><a href="#user-content-fn-1">…</a></sup>
    const ref = container.querySelector(
      'a[href="#user-content-fn-1"]',
    ) as HTMLAnchorElement | null;
    expect(ref).not.toBeNull();

    fireEvent.click(ref!);

    const hl = useChatStore.getState().messageHighlight;
    expect(hl).not.toBeNull();
    expect(hl!.messageId).toBe("msg-42");
    expect(hl!.rowIndices).toEqual([0, 1, 2]);
    expect(typeof hl!.ts).toBe("number");
  });

  it("expands combined inline markers like [^3, 5, 6] into three separate clickable refs", () => {
    const md = [
      "## Direct Answer",
      "Whitney High consistently scores in the mid-600s [^3, 5, 6].",
      "",
      "[^3]: row 3 source {rows=3}",
      "[^5]: row 5 source {rows=5}",
      "[^6]: row 6 source {rows=6}",
    ].join("\n");
    const { container } = render(
      <AnswerChunk content={md} messageId="msg-combined" />,
    );

    // The literal combined form must NOT survive into the DOM.
    expect(container.textContent).not.toContain("[^3, 5, 6]");
    expect(container.textContent).not.toContain("[^3,5,6]");

    // remark-gfm renders each inline marker as <sup><a href="#user-content-fn-N">…</a></sup>.
    const refs = Array.from(
      container.querySelectorAll(
        'a[href^="#user-content-fn-"]',
      ),
    ) as HTMLAnchorElement[];
    // We expect three distinct inline refs (one per id) plus their footnote
    // definitions might also be linked from the references section back-refs;
    // assert at least the three inline anchors exist by id.
    const inlineHrefs = refs
      .map((a) => a.getAttribute("href"))
      .filter((h): h is string => !!h && /^#user-content-fn-\d+$/.test(h));
    expect(inlineHrefs).toEqual(
      expect.arrayContaining([
        "#user-content-fn-3",
        "#user-content-fn-5",
        "#user-content-fn-6",
      ]),
    );

    // Each is wrapped in a <sup> by remark-gfm.
    const supLinks = container.querySelectorAll(
      'sup a[href^="#user-content-fn-"]',
    );
    expect(supLinks.length).toBeGreaterThanOrEqual(3);
  });

  it("does not dispatch when the footnote definition has no rows", () => {
    const md = [
      "## Direct Answer",
      "Bare claim[^1].",
      "",
      "[^1]: bare definition with no rows directive",
    ].join("\n");
    const { container } = render(
      <AnswerChunk content={md} messageId="msg-9" />,
    );
    const ref = container.querySelector(
      'a[href="#user-content-fn-1"]',
    ) as HTMLAnchorElement | null;
    expect(ref).not.toBeNull();
    fireEvent.click(ref!);
    expect(useChatStore.getState().messageHighlight).toBeNull();
  });
});
