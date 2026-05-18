import { describe, it, expect } from "vitest";
import {
  stripAnsiEscapes,
  convertBracketCitationsToFootnotes,
  fixDanglingFootnotes,
} from "./citation-utils";

describe("stripAnsiEscapes", () => {
  it("passes through plain text unchanged", () => {
    expect(stripAnsiEscapes("Hello world")).toBe("Hello world");
  });

  it("strips bold ANSI codes", () => {
    expect(stripAnsiEscapes("\x1b[1mBold\x1b[0m text")).toBe("Bold text");
  });

  it("strips color ANSI codes (foreground 31-36)", () => {
    expect(stripAnsiEscapes("\x1b[31mRed\x1b[0m")).toBe("Red");
    expect(stripAnsiEscapes("\x1b[32mGreen\x1b[0m")).toBe("Green");
  });

  it("strips complex CSI sequences (color codes with semicolons)", () => {
    expect(stripAnsiEscapes("\x1b[38;5;208mOrange\x1b[0m")).toBe("Orange");
  });

  it("handles text with no ANSI escapes", () => {
    const input = "Just some **bold** and *italic* markdown";
    expect(stripAnsiEscapes(input)).toBe(input);
  });

  it("handles empty strings", () => {
    expect(stripAnsiEscapes("")).toBe("");
  });

  it("handles text with only ANSI escape sequences", () => {
    expect(stripAnsiEscapes("\x1b[1m\x1b[31m")).toBe("");
  });
});

describe("convertBracketCitationsToFootnotes", () => {
  it("converts single [[N]] to [^src-N] footnote", () => {
    const { processed } = convertBracketCitationsToFootnotes("See source [[1]].");
    expect(processed).toContain("[^src-1]");
    expect(processed).toContain("[^src-1]: Source 1");
  });

  it("converts multiple distinct [[N]] citations", () => {
    const { processed } = convertBracketCitationsToFootnotes(
      "See [[1]] and [[2]] for details."
    );
    expect(processed).toContain("[^src-1]");
    expect(processed).toContain("[^src-2]");
    expect(processed).toContain("[^src-1]: Source 1");
    expect(processed).toContain("[^src-2]: Source 2");
  });

  it("deduplicates repeated [[N]] references", () => {
    const { processed, footnoteMap } = convertBracketCitationsToFootnotes(
      "Source [[1]] and again [[1]]."
    );
    // Should only have one definition line (not counting inline markers)
    const defMatches = processed.match(/\[\^src-1\]: Source 1/g);
    expect(defMatches).toHaveLength(1);
    // Two inline markers in the body, plus one in the definition = 3 total
    const allRefs = processed.match(/\[\^src-1\]/g);
    expect(allRefs).toHaveLength(3);
    expect(Object.keys(footnoteMap)).toHaveLength(1);
  });

  it("passes through text without bracket citations", () => {
    const { processed, footnoteMap } = convertBracketCitationsToFootnotes(
      "No citations here."
    );
    expect(processed).toBe("No citations here.");
    expect(Object.keys(footnoteMap)).toHaveLength(0);
  });

  it("handles non-numeric bracket content", () => {
    const input = "This is just [[text]] in brackets.";
    const { processed } = convertBracketCitationsToFootnotes(input);
    // Non-numeric [[text]] should be left unchanged
    expect(processed).toContain("[[text]]");
  });

  it("handles empty string", () => {
    const { processed } = convertBracketCitationsToFootnotes("");
    expect(processed).toBe("");
  });

  it("handles citations at start and end of text", () => {
    const { processed } = convertBracketCitationsToFootnotes("[[1]] start [[2]]");
    expect(processed).toMatch(/^\[\^src-1\]/);
    expect(processed).toContain("[^src-2]");
  });

  it("footnoteMap returns correct entries", () => {
    const { footnoteMap } = convertBracketCitationsToFootnotes(
      "Refs [[1]] [[3]] [[1]]"
    );
    expect(footnoteMap).toEqual({
      "src-1": { sourceIndex: 1 },
      "src-3": { sourceIndex: 3 },
    });
  });

  it("sorts definitions by source index", () => {
    const { processed } = convertBracketCitationsToFootnotes(
      "Refs [[3]] [[1]] [[2]]"
    );
    const idx1 = processed.indexOf("[^src-1]: Source 1");
    const idx2 = processed.indexOf("[^src-2]: Source 2");
    const idx3 = processed.indexOf("[^src-3]: Source 3");
    expect(idx1).toBeLessThan(idx2);
    expect(idx2).toBeLessThan(idx3);
  });
});

describe("fixDanglingFootnotes", () => {
  it("passes through text with matching inline refs and definitions", () => {
    const input = "Text with [^1] footnote.\n\n[^1]: My definition";
    expect(fixDanglingFootnotes(input)).toBe(input);
  });

  it("appends synthetic definition for dangling [^N] marker", () => {
    const input = "Text with [^1] but no definition.";
    const result = fixDanglingFootnotes(input);
    expect(result).toContain("[^1]: Source row 1");
  });

  it("handles multiple dangling markers", () => {
    const input = "Refs [^1] and [^2] but no definitions.";
    const result = fixDanglingFootnotes(input);
    expect(result).toContain("[^1]: Source row 1");
    expect(result).toContain("[^2]: Source row 2");
  });

  it("only adds definitions for truly missing ones", () => {
    const input =
      "Refs [^1] and [^2].\n\n[^1]: Existing definition";
    const result = fixDanglingFootnotes(input);
    expect(result).not.toContain("[^1]: Source row 1"); // already exists
    expect(result).toContain("[^2]: Source row 2"); // added
  });

  it("handles text with no inline footnote markers", () => {
    const input = "Just plain text with no footnotes.";
    expect(fixDanglingFootnotes(input)).toBe(input);
  });

  it("sorts synthetic definitions numerically", () => {
    const input = "Refs [^3] and [^1] but no definitions.";
    const result = fixDanglingFootnotes(input);
    const idx1 = result.indexOf("[^1]: Source row 1");
    const idx3 = result.indexOf("[^3]: Source row 3");
    expect(idx1).toBeLessThan(idx3);
  });

  it("handles named (non-numeric) footnote IDs", () => {
    const input = "Named footnote [^note-1] with no definition.";
    const result = fixDanglingFootnotes(input);
    expect(result).toContain("[^note-1]: Source row note-1");
  });

  it("handles empty string", () => {
    expect(fixDanglingFootnotes("")).toBe("");
  });

  it("does not duplicate existing definitions", () => {
    const input =
      "Multiple [^1] refs to same footnote.\n\n[^1]: Already here";
    const result = fixDanglingFootnotes(input);
    const matches = result.match(/\[\^1\]:/g);
    // Should only have the original definition
    expect(matches).toHaveLength(1);
  });
});
