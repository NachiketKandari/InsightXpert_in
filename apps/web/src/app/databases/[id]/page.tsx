"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { ArrowLeft, Play } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { AutoDisableWarning } from "@/components/databases/auto-disable-warning";
import { CostConfirmModal } from "@/components/databases/cost-confirm-modal";
import { ProfileStepper } from "@/components/databases/profile-stepper";
import { SchemaPanel } from "@/components/databases/schema-panel";
import { StageCheckboxGroup } from "@/components/databases/stage-checkbox-group";
import { useProfileRun, type ProfileStep } from "@/hooks/useProfileRun";
import { fetchProfile, fetchSchema } from "@/lib/databases/api";
import {
  PROFILE_STAGE_ORDER,
  type DatabaseProfile,
  type ProfileFlags,
  type SchemaResponse,
} from "@/types/database";

const PENDING_STEPS: ProfileStep[] = PROFILE_STAGE_ORDER.map((stage) => ({
  stage,
  state: "pending",
  durationMs: null,
  batchIndex: null,
  batchTotal: null,
  note: null,
}));

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function DatabaseDetailPage({ params }: PageProps) {
  const { id: rawId } = use(params);
  const dbId = decodeURIComponent(rawId);

  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [profile, setProfile] = useState<DatabaseProfile | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [flags, setFlags] = useState<ProfileFlags>({
    with_summaries: false,
    with_quirks: false,
    with_lsh: false,
    with_vectors: false,
  });

  const { state, start, confirmCost, cancel, reset } = useProfileRun(dbId);

  const loadData = useCallback(async () => {
    const [s, p] = await Promise.all([fetchSchema(dbId), fetchProfile(dbId)]);
    setSchema(s);
    setProfile(p);
    setLoaded(true);
  }, [dbId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // When a run succeeds, refresh the cached profile so the left-column panel
  // picks up freshly-populated summaries.
  useEffect(() => {
    if (state.kind === "succeeded") {
      fetchProfile(dbId).then((p) => setProfile(p));
      toast.success(
        `Profiled ${state.summary.table_count} tables · ${state.summary.column_count} columns`,
      );
    } else if (state.kind === "failed") {
      toast.error(state.message);
    }
  }, [state, dbId]);

  const runInFlight = state.kind === "connecting" || state.kind === "running";
  const showStepper =
    state.kind === "running" ||
    state.kind === "succeeded" ||
    state.kind === "failed" ||
    state.kind === "connecting";

  const totalColumns =
    profile?.tables.reduce((sum, t) => sum + t.columns.length, 0) ??
    (schema?.tables.length ?? 0);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-10 glass border-b border-border px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center gap-3">
          <Link href="/databases">
            <Button variant="ghost" size="icon" className="size-9">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <h1 className="font-mono text-lg font-semibold">{dbId}</h1>
          <Badge variant="outline" className="text-[10px] uppercase">
            {profile ? "profiled" : "not profiled"}
          </Badge>
        </div>
      </header>

      <PageContainer as="main" className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        {/* Left: schema summary */}
        <section>
          <div className="mb-3 flex items-center gap-3 text-xs text-muted-foreground">
            <span>
              {schema?.tables.length ?? 0} table
              {(schema?.tables.length ?? 0) !== 1 ? "s" : ""}
            </span>
            {profile && (
              <>
                <span>·</span>
                <span>{totalColumns} columns</span>
              </>
            )}
          </div>
          {loaded ? (
            <SchemaPanel schema={schema} profile={profile} />
          ) : (
            <div className="rounded-md border border-border p-4 text-sm text-muted-foreground">
              Loading schema…
            </div>
          )}
        </section>

        {/* Right: profiling controls */}
        <aside className="space-y-4">
          <div className="rounded-md border border-border bg-card p-4">
            <h2 className="text-sm font-semibold">Run profiling</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Schema and stats always run. LLM stages are optional — you'll see
              a cost estimate before anything expensive starts.
            </p>

            <div className="mt-4">
              <StageCheckboxGroup
                flags={flags}
                onChange={setFlags}
                disabled={runInFlight}
              />
            </div>

            <div className="mt-4 flex items-center gap-2">
              <Button
                onClick={() => start(flags)}
                disabled={runInFlight}
                className="flex-1"
              >
                <Play className="size-4 mr-1.5" />
                {runInFlight ? "Running…" : "Run profiling"}
              </Button>
              {(state.kind === "succeeded" || state.kind === "failed") && (
                <Button variant="ghost" size="sm" onClick={reset}>
                  Reset
                </Button>
              )}
            </div>
          </div>

          {state.kind === "succeeded" && state.autoDisabled && (
            <AutoDisableWarning columns={state.summary.column_count} />
          )}

          {showStepper && (
            <div className="rounded-md border border-border bg-card p-3">
              <h3 className="mb-2 px-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Progress
              </h3>
              <ProfileStepper
                steps={
                  state.kind === "connecting" ? PENDING_STEPS : state.steps
                }
              />
              {state.kind === "failed" && (
                <p className="mt-2 px-2 text-xs text-red-600 dark:text-red-400">
                  {state.message}
                </p>
              )}
              {state.kind === "succeeded" && (
                <p className="mt-2 px-2 text-xs text-emerald-600 dark:text-emerald-400">
                  Done · {state.summary.summaries_populated} summaries populated
                </p>
              )}
            </div>
          )}
        </aside>
      </PageContainer>

      <CostConfirmModal
        open={state.kind === "awaiting_confirmation"}
        estimate={
          state.kind === "awaiting_confirmation" ? state.estimate : null
        }
        onConfirm={confirmCost}
        onCancel={cancel}
      />
    </div>
  );
}
