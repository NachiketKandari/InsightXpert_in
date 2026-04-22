"use client";

import { Switch } from "@/components/ui/switch";
import type { ProfileFlags } from "@/types/database";

interface StageRow {
  key: keyof ProfileFlags;
  label: string;
  description: string;
  expensive: boolean;
}

const STAGES: readonly StageRow[] = [
  {
    key: "with_summaries",
    label: "Summaries",
    description: "LLM-generated short summary per column (~2s per batch of 20).",
    expensive: true,
  },
  {
    key: "with_quirks",
    label: "Quirks",
    description: "LLM data-quality flags (enum labels, semantic hints, aliases).",
    expensive: true,
  },
  {
    key: "with_lsh",
    label: "LSH index",
    description: "Locality-sensitive hashing for fuzzy-join suggestions (CPU-only).",
    expensive: false,
  },
  {
    key: "with_vectors",
    label: "Vectors",
    description: "Column-embedding vectors for semantic search.",
    expensive: true,
  },
] as const;

interface StageCheckboxGroupProps {
  flags: ProfileFlags;
  onChange: (next: ProfileFlags) => void;
  disabled?: boolean;
}

export function StageCheckboxGroup({
  flags,
  onChange,
  disabled,
}: StageCheckboxGroupProps) {
  return (
    <div className="space-y-3">
      {STAGES.map((s) => (
        <label
          key={s.key}
          className="flex items-start gap-3 rounded-md border border-border p-3 hover:bg-muted/40"
        >
          <Switch
            checked={flags[s.key]}
            onCheckedChange={(checked: boolean) =>
              onChange({ ...flags, [s.key]: checked })
            }
            disabled={disabled}
            className="mt-0.5"
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{s.label}</span>
              {s.expensive && (
                <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-600 dark:text-amber-400">
                  llm
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{s.description}</p>
          </div>
        </label>
      ))}
    </div>
  );
}
