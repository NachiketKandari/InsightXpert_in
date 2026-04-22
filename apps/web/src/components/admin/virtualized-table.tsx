"use client";

// Generic virtualized table built on @tanstack/react-virtual.
// Used by Query Metrics and Audit Log tabs: both paginate with cursors and
// can produce thousands of rows. Columns are caller-defined so we don't grow
// a heavy table abstraction.
//
// Props:
//   - rows: fully flattened list of items
//   - columns: display config with per-row renderer
//   - estimateSize: pixel estimate per row (tune for content)
//   - onEndReached: called when the user scrolls near the bottom — the caller
//     typically triggers the next infinite-query page here
//   - renderExpanded: optional row-expansion renderer. When non-null, rows
//     become clickable and expand to show full detail. Expanded state is
//     single-row (clicking another row collapses the first).

import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export interface VirtualizedColumn<T> {
  key: string;
  header: string;
  width: string; // CSS grid track (e.g. "1fr", "120px")
  render: (row: T) => React.ReactNode;
}

export interface VirtualizedTableProps<T> {
  rows: T[];
  columns: VirtualizedColumn<T>[];
  estimateSize?: number;
  rowKey: (row: T) => string;
  onEndReached?: () => void;
  isFetchingMore?: boolean;
  renderExpanded?: (row: T) => React.ReactNode;
  emptyLabel?: string;
  /** Height of the scrolling viewport in pixels. */
  height?: number;
}

export function VirtualizedTable<T>({
  rows,
  columns,
  estimateSize = 52,
  rowKey,
  onEndReached,
  isFetchingMore,
  renderExpanded,
  emptyLabel = "No results.",
  height = 560,
}: VirtualizedTableProps<T>) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const gridTemplate = [
    renderExpanded ? "32px" : null,
    ...columns.map((c) => c.width),
  ]
    .filter(Boolean)
    .join(" ");

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimateSize,
    overscan: 8,
  });

  // Fire onEndReached when the last virtual item is within 3 rows of the tail.
  useEffect(() => {
    if (!onEndReached || rows.length === 0) return;
    const items = virtualizer.getVirtualItems();
    const last = items[items.length - 1];
    if (!last) return;
    if (last.index >= rows.length - 3 && !isFetchingMore) {
      onEndReached();
    }
  }, [virtualizer, rows.length, onEndReached, isFetchingMore]);

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card">
        <div
          className="grid gap-3 border-b border-border px-5 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground"
          style={{ gridTemplateColumns: gridTemplate }}
        >
          {renderExpanded && <div />}
          {columns.map((c) => (
            <div key={c.key}>{c.header}</div>
          ))}
        </div>
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          {emptyLabel}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div
        className="grid gap-3 border-b border-border px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground"
        style={{ gridTemplateColumns: gridTemplate }}
      >
        {renderExpanded && <div />}
        {columns.map((c) => (
          <div key={c.key}>{c.header}</div>
        ))}
      </div>
      <div
        ref={parentRef}
        style={{ height, overflow: "auto" }}
        className="relative"
      >
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            position: "relative",
            width: "100%",
          }}
        >
          {virtualizer.getVirtualItems().map((v) => {
            const row = rows[v.index];
            const key = rowKey(row);
            const isOpen = expanded === key;
            return (
              <div
                key={key}
                data-index={v.index}
                ref={virtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${v.start}px)`,
                }}
              >
                <div
                  className={cn(
                    "grid items-center gap-3 border-b border-border/50 px-5 py-3 text-sm",
                    renderExpanded && "cursor-pointer hover:bg-muted/40",
                    isOpen && "bg-muted/30",
                  )}
                  style={{ gridTemplateColumns: gridTemplate }}
                  onClick={() => {
                    if (!renderExpanded) return;
                    setExpanded(isOpen ? null : key);
                  }}
                >
                  {renderExpanded && (
                    <ChevronRight
                      className={cn(
                        "size-4 text-muted-foreground transition-transform",
                        isOpen && "rotate-90",
                      )}
                    />
                  )}
                  {columns.map((c) => (
                    <div key={c.key} className="min-w-0 truncate">
                      {c.render(row)}
                    </div>
                  ))}
                </div>
                {isOpen && renderExpanded && (
                  <div className="border-b border-border/50 bg-muted/20 px-4 py-3">
                    {renderExpanded(row)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {isFetchingMore && (
        <div className="flex items-center justify-center border-t border-border py-2 text-xs text-muted-foreground">
          Loading more…
        </div>
      )}
    </div>
  );
}
