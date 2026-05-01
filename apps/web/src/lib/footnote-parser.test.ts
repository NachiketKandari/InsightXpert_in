import { describe, it, expect } from "vitest";
import {
  parseRowsSpec,
  parseFootnoteRowMap,
  stripRowsDirectives,
} from "./footnote-parser";

describe("parseRowsSpec", () => {
  it("converts single 1-based index to 0-based", () => {
    expect(parseRowsSpec("5")).toEqual([4]);
  });

  it("expands a comma list", () => {
    expect(parseRowsSpec("1,3,5")).toEqual([0, 2, 4]);
  });

  it("expands an inclusive range", () => {
    expect(parseRowsSpec("1-3")).toEqual([0, 1, 2]);
  });

  it("expands combinations of single, list, and range", () => {
    expect(parseRowsSpec("1,3-5,8")).toEqual([0, 2, 3, 4, 7]);
  });

  it("returns [] for empty spec", () => {
    expect(parseRowsSpec("")).toEqual([]);
    expect(parseRowsSpec("   ")).toEqual([]);
  });

  it("ignores garbage entries without throwing", () => {
    expect(parseRowsSpec("foo,2,bar")).toEqual([1]);
  });

  it("dedupes overlapping indices preserving first occurrence", () => {
    expect(parseRowsSpec("1-3,2,4")).toEqual([0, 1, 2, 3]);
  });
});

describe("parseFootnoteRowMap", () => {
  it("extracts rows directives from a multi-footnote block", () => {
    const md = [
      "Some answer body.",
      "",
      "[^1]: schools table — 49 metadata columns {rows=1}",
      "[^2]: satscores.NumGE1500 average {rows=1-3}",
      "[^3]: frpm Enrollment column {rows=2,5,7}",
    ].join("\n");
    expect(parseFootnoteRowMap(md)).toEqual({
      "1": [0],
      "2": [0, 1, 2],
      "3": [1, 4, 6],
    });
  });

  it("returns [] for a footnote definition with no {rows=...}", () => {
    const md = "[^1]: bare definition with no directive";
    expect(parseFootnoteRowMap(md)).toEqual({ "1": [] });
  });

  it("returns [] for an empty {rows=} directive (malformed)", () => {
    const md = "[^4]: empty rows {rows=}";
    expect(parseFootnoteRowMap(md)).toEqual({ "4": [] });
  });

  it("returns {} when no footnote definitions exist", () => {
    expect(parseFootnoteRowMap("just some prose")).toEqual({});
  });

  it("does not throw on malformed directives", () => {
    const md = "[^1]: weird {rows=abc}";
    expect(parseFootnoteRowMap(md)).toEqual({ "1": [] });
  });
});

describe("stripRowsDirectives", () => {
  it("removes the directive and the leading whitespace", () => {
    const md = "[^1]: schools table — 49 metadata columns {rows=1}";
    expect(stripRowsDirectives(md)).toBe(
      "[^1]: schools table — 49 metadata columns",
    );
  });

  it("removes multiple directives", () => {
    const md = "a {rows=1} and b {rows=2-4}";
    expect(stripRowsDirectives(md)).toBe("a and b");
  });
});
