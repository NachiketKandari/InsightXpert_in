"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { ArrowLeft, Play, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { AutoDisableWarning } from "@/components/databases/auto-disable-warning";
import { ProfileStepper } from "@/components/databases/profile-stepper";
import { SchemaPanel } from "@/components/databases/schema-panel";
import { StageCheckboxGroup } from "@/components/databases/stage-checkbox-group";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProfileRun, type ProfileStep } from "@/hooks/useProfileRun";
import {
  deleteProfile,
  fetchProfile,
  fetchProfileDefaults,
  fetchSchema,
  type ProfileDefaultsResponse,
} from "@/lib/databases/api";
import {
  PROFILE_STAGE_ORDER,
  type DatabaseProfile,
  type ProfileCostEstimatePayload,
  type ProfileFlags,
  type SchemaResponse,
} from "@/types/database";

const EMPTY_FLAGS: ProfileFlags = {
  with_summaries: false,
  with_quirks: false,
  with_lsh: false,
  with_vectors: false,
  with_table_descriptions: false,
};

const PENDING_STEPS: ProfileStep[] = PROFILE_STAGE_ORDER.map((stage) => ({
  stage,
  state: "pending",
  durationMs: null,
  batchIndex: null,
  batchTotal: null,
  note: null,
}));

function mergeDefaults(
  defaults: Partial<ProfileFlags> | undefined,
): ProfileFlags {
  return { ...EMPTY_FLAGS, ...defaults };
}

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function DatabaseDetailPage({ params }: PageProps) {
  const { id: rawId } = use(params);
  const dbId = decodeURIComponent(rawId);

  const { isAdmin } = useCurrentUser();
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [profile, setProfile] = useState<DatabaseProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [schemaLoading, setSchemaLoading] = useState(true);
  const [defaults, setDefaults] = useState<ProfileDefaultsResponse | null>(null);
  const [flags, setFlags] = useState<ProfileFlags>(EMPTY_FLAGS);

  const { state, start, confirmCost, reset } = useProfileRun(dbId);

  // Fetch profile defaults from server on mount.
  useEffect(() => {
    fetchProfileDefaults().then((d) => {
      if (d) {
        setDefaults(d);
        setFlags(mergeDefaults(d.flags));
      }
    });
  }, []);

  const [costEstimate, setCostEstimate] =
    useState<ProfileCostEstimatePayload | null>(null);

  // Auto-confirm the cost-gate handshake — no blocking modal.
  useEffect(() => {
    if (state.kind === "awaiting_confirmation") {
      setCostEstimate(state.estimate);
      confirmCost();
    }
  }, [state, confirmCost]);

  const loadData = useCallback(async () => {
    setSchemaLoading(true);
    setProfileLoading(true);

    const [schemaResult, profileResult] = await Promise.allSettled([
      fetchSchema(dbId),
      fetchProfile(dbId),
    ]);

    if (schemaResult.status === "fulfilled") setSchema(schemaResult.value);
    if (profileResult.status === "fulfilled") setProfile(profileResult.value);

    setSchemaLoading(false);
    setProfileLoading(false);
  }, [dbId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // When a run succeeds, refresh profile data so the UI updates immediately
  // without requiring a page navigation. On failure, show an error toast.
  useEffect(() => {
    if (state.kind === "succeeded") {
      toast.success(
        `Profiled ${state.summary.table_count} tables · ${state.summary.column_count} columns`,
      );
      loadData();
    } else if (state.kind === "failed") {
      toast.error(state.message);
    }
  }, [state, dbId, loadData]);

  const handleDeleteProfile = useCallback(async () => {
    if (!confirm("Delete all profiled data for this database? This cannot be undone.")) return;
    const ok = await deleteProfile(dbId);
    if (ok) {
      setProfile(null);
      reset();
      toast.success("Profile data deleted");
    } else {
      toast.error("Failed to delete profile");
    }
  }, [dbId, reset]);

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
            {profileLoading ? (
              <span className="inline-flex items-center gap-1">
                <span className="inline-block size-2 animate-pulse rounded-full bg-muted-foreground/40" />
                loading
              </span>
            ) : profile ? (
              "profiled"
            ) : (
              "not profiled"
            )}
          </Badge>
        </div>
      </header>

      <PageContainer as="main" className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        {/* Left: schema summary */}
        <section>
          <div className="mb-3 flex items-center gap-3 text-xs text-muted-foreground">
            {schemaLoading ? (
              <span className="inline-block h-3 w-16 animate-pulse rounded bg-muted" />
            ) : (
              <span>
                {schema?.tables.length ?? 0} table
                {(schema?.tables.length ?? 0) !== 1 ? "s" : ""}
              </span>
            )}
            {profile && (
              <>
                <span>·</span>
                <span>{totalColumns} columns</span>
              </>
            )}
          </div>
          {!schemaLoading ? (
            <SchemaPanel
              schema={schema}
              profile={profile}
              dbId={dbId}
              onProfileRefresh={() =>
                fetchProfile(dbId).then((p) => setProfile(p))
              }
            />
          ) : (
            <div className="rounded-md border border-border p-4 text-sm text-muted-foreground">
              Loading schema…
            </div>
          )}
        </section>

        {/* Right: profiling controls */}
        <aside className="space-y-4 md:sticky md:top-[57px] md:self-start">
          <div className="rounded-md border border-border bg-card p-4">
            <h2 className="text-sm font-semibold">Run profiling</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Schema and stats always run. LLM stages are optional and will show
              a cost estimate when the run starts.
            </p>

            {isAdmin ? (
              <>
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
              </>
            ) : (
              <div className="mt-4">
                <Button
                  onClick={() => start(flags)}
                  disabled={runInFlight}
                  className="w-full"
                >
                  <Play className="size-4 mr-1.5" />
                  {runInFlight ? "Running…" : "Run profiling"}
                </Button>
                {(state.kind === "succeeded" || state.kind === "failed") && (
                  <div className="mt-2">
                    <Button variant="ghost" size="sm" onClick={reset} className="w-full">
                      Reset
                    </Button>
                  </div>
                )}
              </div>
            )}

            {profile && !runInFlight && (
              <div className="mt-3 pt-3 border-t border-border">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full text-muted-foreground hover:text-destructive"
                  onClick={handleDeleteProfile}
                >
                  <Trash2 className="size-3.5 mr-1.5" />
                  Delete profile data
                </Button>
              </div>
            )}
          </div>

          {state.kind === "succeeded" && state.autoDisabled && (
            <AutoDisableWarning columns={state.summary.column_count} />
          )}

          {showStepper && (
            <div className="rounded-md border border-border bg-card p-3">
              <h3 className="mb-2 px-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Progress
              </h3>
              {costEstimate && (
                <div className="mb-3 rounded bg-accent/40 px-3 py-2 text-xs text-muted-foreground">
                  <span className="font-medium">Estimate:</span>{" "}
                  {costEstimate.columns} columns ·{" "}
                  {costEstimate.total_llm_calls} LLM call
                  {costEstimate.total_llm_calls !== 1 ? "s" : ""} · ~
                  {costEstimate.estimated_seconds}s
                  {costEstimate.provider && (
                    <>
                      {" "}
                      · {costEstimate.provider}
                      {costEstimate.model && <>/{costEstimate.model}</>}
                    </>
                  )}
                </div>
              )}
              <ProfileStepper
                steps={
                  state.kind === "connecting" ? PENDING_STEPS : state.steps
                }
                totalDurationMs={
                  state.kind === "succeeded"
                    ? state.summary.total_duration_ms
                    : null
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
    </div>
  );
}
