import { describe, expect, it } from "vitest";

import {
  clearVisible,
  filterTables,
  formatRowCount,
  isUnsupported,
  selectableTables,
  selectAllVisible,
  toggleSelection,
} from "./tables";

describe("filterTables", () => {
  it("returns all tables on empty query", () => {
    expect(filterTables(["EMP", "DEPT"], "  ")).toEqual(["EMP", "DEPT"]);
  });

  it("matches case-insensitively", () => {
    expect(filterTables(["EMPLOYEES", "DEPT", "emp_history"], "emp")).toEqual([
      "EMPLOYEES",
      "emp_history",
    ]);
  });
});

describe("selection helpers", () => {
  it("toggles a table in and out", () => {
    expect(toggleSelection([], "A")).toEqual(["A"]);
    expect(toggleSelection(["A", "B"], "A")).toEqual(["B"]);
  });

  it("select-all unions visible without duplicates", () => {
    expect(selectAllVisible(["A"], ["A", "B"])).toEqual(["A", "B"]);
  });

  it("clear removes only visible tables", () => {
    expect(clearVisible(["A", "B", "C"], ["A", "B"])).toEqual(["C"]);
  });
});

describe("unsupported tables", () => {
  const details = {
    EMP: { row_count: 10, column_count: 2, unsupported_columns: [] },
    DOCS: { row_count: null, column_count: 1, unsupported_columns: ["PAYLOAD: BLOB"] },
  };

  it("flags tables with unsupported columns", () => {
    expect(isUnsupported(details, "EMP")).toBe(false);
    expect(isUnsupported(details, "DOCS")).toBe(true);
    expect(isUnsupported(undefined, "DOCS")).toBe(false);
  });

  it("selectableTables excludes blocked tables", () => {
    expect(selectableTables(["EMP", "DOCS"], details)).toEqual(["EMP"]);
  });
});

describe("formatRowCount", () => {
  it("formats counts and unknown", () => {
    expect(formatRowCount(12400)).toBe("12,400 rows");
    expect(formatRowCount(0)).toBe("0 rows");
    expect(formatRowCount(null)).toBe("—");
  });
});
