// Pure helpers for the connect-dialog table picker (search + select-all).
//
// Kept dependency-free so they are trivially unit-testable; the dialog
// component owns all React state and server interaction.

export interface TableDetails {
  row_count: number | null;
  column_count: number;
  unsupported_columns: string[];
}

export type TableDetailsMap = Record<string, TableDetails>;

/** Case-insensitive substring filter over table names. Empty query = all. */
export function filterTables(tables: string[], query: string): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...tables];
  return tables.filter((t) => t.toLowerCase().includes(q));
}

/** Toggle one table in the selection. */
export function toggleSelection(selected: string[], name: string): string[] {
  return selected.includes(name)
    ? selected.filter((t) => t !== name)
    : [...selected, name];
}

/** Add every visible table to the selection (select-all). */
export function selectAllVisible(selected: string[], visible: string[]): string[] {
  const next = new Set(selected);
  for (const t of visible) next.add(t);
  return [...next];
}

/** Remove every visible table from the selection (clear). */
export function clearVisible(selected: string[], visible: string[]): string[] {
  const hide = new Set(visible);
  return selected.filter((t) => !hide.has(t));
}

/** True when the table is blocked in v1 (binary column types). */
export function isUnsupported(
  details: TableDetailsMap | undefined,
  name: string,
): boolean {
  return (details?.[name]?.unsupported_columns.length ?? 0) > 0;
}

/** Selectable tables only (unsupported ones can never be saved). */
export function selectableTables(
  tables: string[],
  details: TableDetailsMap | undefined,
): string[] {
  return tables.filter((t) => !isUnsupported(details, t));
}

/** "12,400 rows" / "—" when the count is unknown (timed out). */
export function formatRowCount(rowCount: number | null): string {
  if (rowCount === null || rowCount === undefined) return "—";
  return `${rowCount.toLocaleString("en-US")} rows`;
}
