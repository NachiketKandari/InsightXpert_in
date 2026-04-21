// Typed Automations API client (Phase C1).
// Centralizes every /api/v1/automations/* and /api/v1/notifications/* call
// behind a narrowly typed surface. Consumers (stores, components, hooks)
// should NOT fetch these endpoints directly.
//
// Contract mirrors backend plan §1 exactly. Any drift here should be
// accompanied by a matching backend change.

import { apiCall, apiFetch } from "@/lib/api";
import type {
  Automation,
  AutomationRun,
  CreateAutomationPayload,
  Notification,
  TriggerCondition,
  TriggerTemplate,
} from "@/types/automation";

// ----------------------------------------------------------------------------
// Automations CRUD
// ----------------------------------------------------------------------------

export function fetchAutomations(): Promise<Automation[] | null> {
  return apiCall<Automation[]>("/api/v1/automations");
}

export function fetchAutomation(id: string): Promise<Automation | null> {
  return apiCall<Automation>(`/api/v1/automations/${id}`);
}

export function createAutomation(
  payload: CreateAutomationPayload,
): Promise<Automation | null> {
  return apiCall<Automation>("/api/v1/automations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAutomation(
  id: string,
  payload: Partial<CreateAutomationPayload>,
): Promise<Automation | null> {
  return apiCall<Automation>(`/api/v1/automations/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteAutomation(id: string): Promise<boolean> {
  const res = await apiFetch(`/api/v1/automations/${id}`, { method: "DELETE" });
  return res.ok;
}

export function toggleAutomation(id: string): Promise<Automation | null> {
  return apiCall<Automation>(`/api/v1/automations/${id}/toggle`, {
    method: "POST",
  });
}

// Backend contract: POST /api/v1/automations/{id}/runs creates a manual run.
export function runAutomationNow(
  id: string,
): Promise<{ status: string; message: string; run: AutomationRun | null } | null> {
  return apiCall<{ status: string; message: string; run: AutomationRun | null }>(
    `/api/v1/automations/${id}/runs`,
    { method: "POST" },
  );
}

export async function fetchRunHistory(
  id: string,
  limit = 20,
): Promise<AutomationRun[] | null> {
  return apiCall<AutomationRun[]>(
    `/api/v1/automations/${id}/runs?limit=${limit}`,
  );
}

// ----------------------------------------------------------------------------
// NL → TriggerCondition compile, AI → SQL generation
// ----------------------------------------------------------------------------

export function compileTrigger(
  nl_text: string,
  available_columns: string[] | null = null,
): Promise<TriggerCondition | null> {
  return apiCall<TriggerCondition>("/api/v1/automations/compile-trigger", {
    method: "POST",
    body: JSON.stringify({ nl_text, available_columns }),
  });
}

export function generateSql(
  prompt: string,
): Promise<{ sql: string; explanation: string | null } | null> {
  return apiCall<{ sql: string; explanation: string | null }>(
    "/api/v1/automations/generate-sql",
    {
      method: "POST",
      body: JSON.stringify({ prompt }),
    },
  );
}

// ----------------------------------------------------------------------------
// Trigger Templates
// Backend nests templates under the automations prefix:
//   /api/v1/automations/templates, /api/v1/automations/templates/{id}
// ----------------------------------------------------------------------------

export function fetchTriggerTemplates(): Promise<TriggerTemplate[] | null> {
  return apiCall<TriggerTemplate[]>("/api/v1/automations/templates");
}

export function createTriggerTemplate(
  name: string,
  description: string | null,
  conditions: TriggerCondition[],
): Promise<TriggerTemplate | null> {
  return apiCall<TriggerTemplate>("/api/v1/automations/templates", {
    method: "POST",
    body: JSON.stringify({ name, description, conditions }),
  });
}

export function updateTriggerTemplate(
  id: string,
  payload: { name?: string; description?: string | null; conditions?: TriggerCondition[] },
): Promise<TriggerTemplate | null> {
  return apiCall<TriggerTemplate>(`/api/v1/automations/templates/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteTriggerTemplate(id: string): Promise<boolean> {
  const res = await apiFetch(`/api/v1/automations/templates/${id}`, {
    method: "DELETE",
  });
  return res.ok;
}

// ----------------------------------------------------------------------------
// Notifications
// ----------------------------------------------------------------------------

export function fetchNotifications(
  unreadOnly = false,
): Promise<Notification[] | null> {
  const qs = unreadOnly ? "?unread=true" : "";
  return apiCall<Notification[]>(`/api/v1/notifications${qs}`);
}

export function fetchAllNotifications(
  unreadOnly = false,
): Promise<Notification[] | null> {
  // Admin-scoped — backend mirrors the list endpoint under /all.
  const qs = unreadOnly ? "?unread=true" : "";
  return apiCall<Notification[]>(`/api/v1/notifications/all${qs}`);
}

export async function markNotificationRead(id: string): Promise<boolean> {
  const res = await apiFetch(`/api/v1/notifications/${id}/read`, {
    method: "POST",
  });
  return res.ok;
}

export async function markAllNotificationsRead(): Promise<boolean> {
  const res = await apiFetch(`/api/v1/notifications/mark-all-read`, {
    method: "POST",
  });
  return res.ok;
}

export function fetchUnreadCount(): Promise<{ count: number } | null> {
  return apiCall<{ count: number }>("/api/v1/notifications/count");
}
