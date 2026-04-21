"use client";

// Phase C1 New-Automation dialog. Replaces the workflow-canvas builder (deferred
// to C2) with a straightforward form:
//   1. Name + description
//   2. Target database
//   3. SQL (hand-edit or generate via AI)
//   4. Schedule (preset or custom cron)
//   5. Trigger conditions (plus templates)
// Uses the already-ported small components: SchedulePicker,
// TriggerConditionBuilder, TriggerTemplatePicker, AiSqlGenerator, SqlEditorModal.

import React, { useEffect, useMemo, useState } from "react";
import { Loader2, Save, Database, Pencil } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiCall } from "@/lib/api";
import { useAutomationStore } from "@/stores/automation-store";
import { SCHEDULE_PRESETS } from "@/lib/automation-utils";
import type { DatasetInfo } from "@/types/dataset";
import type {
  CreateAutomationPayload,
  SchedulePreset,
  TriggerCondition,
} from "@/types/automation";
import { SchedulePicker } from "./schedule-picker";
import { TriggerConditionBuilder } from "./trigger-condition-builder";
import { TriggerTemplatePicker } from "./trigger-template-picker";
import { AiSqlGenerator } from "./ai-sql-generator";
import { SqlEditorModal } from "./sql-editor-modal";

interface NewAutomationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function NewAutomationDialog({ open, onOpenChange }: NewAutomationDialogProps) {
  const createAutomation = useAutomationStore((s) => s.createAutomation);
  const fetchTemplates = useAutomationStore((s) => s.fetchTriggerTemplates);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sql, setSql] = useState("");
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [dbId, setDbId] = useState<string>("");
  const [schedulePreset, setSchedulePreset] = useState<SchedulePreset>("daily");
  const [customCron, setCustomCron] = useState("0 9 * * *");
  const [conditions, setConditions] = useState<TriggerCondition[]>([]);
  const [sqlEditorOpen, setSqlEditorOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Reset form only on the open-transition (closed → open). Guarded by a ref
  // so the lint rule "set-state-in-effect" stays happy — no cascading renders
  // on each re-render while already open.
  const wasOpenRef = React.useRef(false);
  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) return;
    wasOpenRef.current = true;
    setName("");
    setDescription("");
    setSql("");
    setSchedulePreset("daily");
    setCustomCron("0 9 * * *");
    setConditions([]);
    fetchTemplates();
    apiCall<DatasetInfo[]>("/api/v1/datasets/public").then((data) => {
      if (data) {
        setDatasets(data);
        const active = data.find((d) => d.is_active);
        if (active) setDbId(active.id);
        else if (data[0]) setDbId(data[0].id);
      }
    });
  }, [open, fetchTemplates]);

  const cronExpression = useMemo(() => {
    if (schedulePreset === "custom") return customCron;
    return SCHEDULE_PRESETS[schedulePreset as keyof typeof SCHEDULE_PRESETS] ?? "";
  }, [schedulePreset, customCron]);

  const canSubmit =
    name.trim().length > 0 &&
    sql.trim().length > 0 &&
    dbId.length > 0 &&
    cronExpression.length > 0 &&
    !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);

    const payload: CreateAutomationPayload = {
      name: name.trim(),
      description: description.trim() || undefined,
      nl_query: name.trim(), // for form-based flow, use name as NL description
      sql_queries: [sql.trim()],
      db_id: dbId,
      schedule_preset: schedulePreset === "custom" ? undefined : schedulePreset,
      cron_expression: cronExpression,
      trigger_conditions: conditions,
    };

    const created = await createAutomation(payload);
    setSubmitting(false);
    if (created) {
      toast.success("Automation created");
      onOpenChange(false);
    } else {
      toast.error("Failed to create automation");
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-2xl w-[92vw] max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>New Automation</DialogTitle>
            <DialogDescription>
              Schedule a query to run on a cadence and notify you when triggers fire.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5 py-2">
            {/* Name + description */}
            <div className="space-y-2">
              <Label htmlFor="automation-name">Name</Label>
              <Input
                id="automation-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Daily transaction fraud check"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="automation-description">Description (optional)</Label>
              <Textarea
                id="automation-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this automation check?"
                rows={2}
                className="resize-none"
              />
            </div>

            {/* Database selector */}
            <div className="space-y-2">
              <Label htmlFor="automation-db">Database</Label>
              <Select value={dbId} onValueChange={setDbId}>
                <SelectTrigger id="automation-db">
                  <SelectValue placeholder="Select a database" />
                </SelectTrigger>
                <SelectContent>
                  {datasets.map((ds) => (
                    <SelectItem key={ds.id} value={ds.id}>
                      <span className="inline-flex items-center gap-2">
                        <Database className="size-3.5 text-muted-foreground" />
                        {ds.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* SQL */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="automation-sql">SQL query</Label>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  disabled={!sql.trim()}
                  onClick={() => setSqlEditorOpen(true)}
                >
                  <Pencil className="size-3.5 mr-1.5" />
                  Edit + Run
                </Button>
              </div>
              <Textarea
                id="automation-sql"
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                placeholder="SELECT COUNT(*) FROM transactions WHERE fraud_flag = 1"
                rows={5}
                className="font-mono text-xs resize-none"
              />
              <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
                  Generate SQL with AI
                </p>
                <AiSqlGenerator
                  onGenerated={(generated) => setSql(generated)}
                />
              </div>
            </div>

            {/* Schedule */}
            <div className="space-y-2">
              <Label>Schedule</Label>
              <SchedulePicker
                preset={schedulePreset}
                customCron={customCron}
                onChange={(p, c) => {
                  setSchedulePreset(p);
                  setCustomCron(c);
                }}
              />
            </div>

            {/* Trigger conditions */}
            <div className="space-y-2">
              <Label>Trigger conditions</Label>
              <TriggerTemplatePicker
                conditions={conditions}
                onConditionsChange={setConditions}
              />
              <TriggerConditionBuilder
                conditions={conditions}
                onChange={setConditions}
                columns={[]}
                resultShape="scalar"
              />
              <p className="text-[11px] text-muted-foreground">
                Leave empty to always notify on successful runs.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={!canSubmit}>
              {submitting ? (
                <>
                  <Loader2 className="size-4 mr-1.5 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Save className="size-4 mr-1.5" />
                  Create Automation
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SqlEditorModal
        title="SQL Query"
        sql={sql}
        isOpen={sqlEditorOpen}
        onClose={() => setSqlEditorOpen(false)}
        onSave={(newSql) => setSql(newSql)}
      />
    </>
  );
}
