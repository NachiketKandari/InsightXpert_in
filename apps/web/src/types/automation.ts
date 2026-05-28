// Phase C1: Automations domain types (slope-free, workflow-canvas-free).
// Workflow canvas is deferred to Phase C2 — `workflow_graph_json` is a
// pass-through byte reservation on the backend. We intentionally do not
// model it on the frontend.

export type TriggerType =
  | "threshold"
  | "change_detection"
  | "row_count"
  | "column_expression";

export interface TriggerCondition {
  type: TriggerType;
  column?: string | null;
  operator?: string | null; // gt, gte, lt, lte, eq, ne
  value?: number | null;
  change_percent?: number | null;
  scope?: "any_row" | "all_rows" | null;
  // Populated by the NL compile endpoint; kept purely for display.
  nl_text?: string | null;
}

export interface TriggerResult {
  condition: TriggerCondition;
  fired: boolean;
  actual_value: number | null;
  message: string;
}

export interface Automation {
  id: string;
  name: string;
  description: string | null;
  nl_query: string;
  /** Legacy single-query mirror (backend may continue to expose for back-compat). */
  sql_query?: string;
  sql_queries: string[];
  db_id: string;
  cron_expression: string;
  trigger_conditions: TriggerCondition[];
  is_active: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  owner_user_id?: string;
  created_by?: string;
  source_conversation_id: string | null;
  source_message_id: string | null;
  created_at: number;
  updated_at: string;
}

export interface AutomationRun {
  id: string;
  automation_id: string;
  status: "success" | "no_trigger" | "error" | "skipped";
  result_json: {
    columns: string[];
    rows: Record<string, unknown>[];
    step_results?: { columns: string[]; rows: Record<string, unknown>[] }[];
  } | null;
  row_count: number | null;
  execution_time_ms: number | null;
  triggers_fired: TriggerResult[] | null;
  error_message: string | null;
  created_at: number;
}

export interface Notification {
  id: string;
  user_id: string;
  automation_id: string | null;
  run_id: string | null;
  title: string;
  message: string;
  severity: "info" | "success" | "warning" | "error" | "critical";
  is_read: boolean;
  automation_name?: string | null;
  created_at: number;
  // Present in admin-scoped responses (/api/v1/notifications/all)
  user_email?: string;
  user_is_admin?: boolean;
}

export interface TriggerTemplate {
  id: string;
  name: string;
  description: string | null;
  conditions: TriggerCondition[];
  created_by?: string;
  owner_user_id?: string;
  created_at: number;
  updated_at: string;
}

export type SchedulePreset = "hourly" | "daily" | "weekly" | "monthly" | "custom";

export interface CreateAutomationPayload {
  name: string;
  description?: string;
  nl_query: string;
  sql_queries: string[];
  db_id: string;
  schedule_preset?: string;
  cron_expression?: string;
  trigger_conditions: TriggerCondition[];
  source_conversation_id?: string;
  source_message_id?: string;
}
