import * as XLSX from "xlsx";
import type { DatabaseProfile } from "@/types/database";

const MAX_SHEET_NAME_LEN = 31;

function sanitizeSheetName(name: string): string {
  return name.replace(/[\\\/\*\?\[\]:]/g, "_").slice(0, MAX_SHEET_NAME_LEN);
}

function dedupeSheetNames(names: string[]): string[] {
  const seen = new Map<string, number>();
  return names.map((name) => {
    const count = seen.get(name) ?? 0;
    seen.set(name, count + 1);
    if (count === 0) return name;
    const suffix = `_${count}`;
    const base = name.slice(0, MAX_SHEET_NAME_LEN - suffix.length);
    return base + suffix;
  });
}

function fmt(val: unknown): string {
  if (val == null) return "";
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (Array.isArray(val)) return val.map((v) => String(v)).join("; ");
  if (typeof val === "object") {
    return Object.entries(val as Record<string, unknown>)
      .map(([k, v]) => `${k}=${v}`)
      .join("; ");
  }
  return String(val);
}

export function downloadProfileXlsx(profile: DatabaseProfile): void {
  const wb = XLSX.utils.book_new();

  // --- Overview sheet ---
  const overviewRows = profile.tables.map((t) => ({
    Table: t.name,
    "Row Count": t.row_count,
    "Column Count": t.columns.length,
    Description: t.description || "",
  }));
  const overviewWs = XLSX.utils.json_to_sheet(overviewRows);
  XLSX.utils.book_append_sheet(wb, overviewWs, "_Overview");

  // --- Per-table sheets ---
  const rawNames = profile.tables.map((t) => sanitizeSheetName(t.name));
  const sheetNames = dedupeSheetNames(rawNames);

  profile.tables.forEach((table, i) => {
    const rows = table.columns.map((col) => ({
      Column: col.name,
      Type: col.type,
      Count: col.stats.count,
      "Null Count": col.stats.null_count,
      "Distinct Count": col.stats.distinct_count,
      Min: col.stats.min_value ?? "",
      Max: col.stats.max_value ?? "",
      "Short Summary": col.short_summary,
      "Long Summary": col.long_summary,
      "BIRD Summary": col.bird_enriched_summary,
      "Semantic Hint": col.quirks.semantic_hint ?? "",
      "Enum Labels": fmt(col.quirks.enum_labels),
      Aliases: fmt(col.quirks.aliases),
      Symbolic: col.quirks.symbolic_values ? "Yes" : "No",
      "Numbered Group": col.quirks.numbered_group ?? "",
      "FK Alias": col.quirks.fk_alias ?? "",
      "Type Mismatch": col.quirks.type_mismatch ?? "",
      "Sample Values": col.stats.sample_values.slice(0, 10).join(", "),
    }));

    const ws = XLSX.utils.json_to_sheet(rows);
    XLSX.utils.book_append_sheet(wb, ws, sheetNames[i]);
  });

  const buf = XLSX.write(wb, { bookType: "xlsx", type: "array" });
  const blob = new Blob([buf], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${profile.db_id}_profile.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}
