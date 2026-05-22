import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { AnswerChunk } from "./answer-chunk";

describe("AnswerChunk", () => {
  it("strips [[N]] bracket citation markers from rendered text", () => {
    const md =
      "Revenue grew 15% [[1]] driven by enterprise expansion [[2]] in North America.";
    const { container } = render(<AnswerChunk content={md} />);
    expect(container.textContent).not.toContain("[[1]]");
    expect(container.textContent).not.toContain("[[2]]");
    expect(container.textContent).toContain("Revenue grew 15%");
    expect(container.textContent).toContain("enterprise expansion");
  });

  it("strips [^...]: footnote definition lines", () => {
    const md = [
      "## Direct Answer",
      "The schools table has 49 columns.",
      "",
      "[^1]: schools table — 49 metadata columns {rows=1}",
    ].join("\n");
    const { container } = render(<AnswerChunk content={md} />);
    expect(container.textContent).not.toContain("[^1]:");
    expect(container.textContent).not.toContain("{rows=");
    expect(container.textContent).toContain("schools table");
  });

  it("renders sections with collapsible secondary sections", () => {
    const md = [
      "## Direct Answer",
      "Primary content here.",
      "",
      "## Data Provenance",
      "Secondary content here.",
    ].join("\n");
    const { container } = render(<AnswerChunk content={md} />);
    expect(container.textContent).toContain("Direct Answer");
    expect(container.textContent).toContain("Data Provenance");
    expect(container.textContent).toContain("Primary content here");
  });

  it("renders plain markdown when no sections are detected", () => {
    const md = "Just a plain paragraph with no headers.";
    const { container } = render(<AnswerChunk content={md} />);
    expect(container.textContent).toContain("Just a plain paragraph");
  });

  it("renders external links correctly", () => {
    const md = "See [the docs](https://example.com) for more.";
    const { container } = render(<AnswerChunk content={md} />);
    const link = container.querySelector('a[href="https://example.com"]');
    expect(link).not.toBeNull();
  });
});
