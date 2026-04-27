// Zod schemas for the create-automation form. Surfaces per-field errors so
// the dialog can replace its previous hand-rolled `canSubmit` boolean with
// schema-driven validation.

import { z } from "zod";

export const triggerConditionSchema = z.object({
  type: z.enum([
    "threshold",
    "row_count",
    "change_detection",
    "column_expression",
  ]),
  column: z.string().optional(),
  operator: z.string().optional(),
  value: z.union([z.string(), z.number(), z.boolean(), z.null()]).optional(),
  change_percent: z.number().optional(),
  scope: z.string().optional(),
  nl_text: z.string().optional(),
});

// Mirrors CreateAutomationPayload as constructed by new-automation-dialog.tsx:
// sql_queries is an array of plain SQL strings (not objects), and the schedule
// is provided via cron_expression.
export const createAutomationSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(120, "Name too long"),
  db_id: z.string().min(1, "Database is required"),
  cron_expression: z.string().min(1, "Schedule is required"),
  sql_queries: z
    .array(z.string().trim().min(1, "SQL query cannot be empty"))
    .min(1, "At least one SQL query required"),
  trigger_conditions: z.array(triggerConditionSchema).default([]),
});

export type CreateAutomationInput = z.infer<typeof createAutomationSchema>;

export type CreateAutomationFieldErrors = Partial<
  Record<keyof CreateAutomationInput, string[]>
>;
