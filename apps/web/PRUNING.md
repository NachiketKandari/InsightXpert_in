# apps/web — Pruning checklist (DEFERRED to Phase B)

This directory is a verbatim fork of `/Users/nachiket/workspace/github.com/public/InsightXpert/frontend` copied on 2026-04-21.

**IMPORTANT (2026-04-21 priority update):** Do NOT prune yet. Phase A = build the backend first so the forked FE works end-to-end. This prune list applies in Phase B, after the core flow is running. Admin/org/voice/automations pages that never get navigated to in the normal flow don't block anything.

When Phase B starts: each item below = delete files + remove references + drop deps from `package.json`.

## Remove (not in v1 scope)

- [ ] **Org/multi-tenant** — finish `docs/org-removal-plan.md` removal inside this dir.
- [ ] **Voice input** — `src/hooks/use-voice-input.ts`, voice button in `src/components/chat/input-toolbar.tsx`, Deepgram dep from `package.json`.
- [ ] **Ollama management UI** — any component calling `/api/ollama/*`, model-pull dialog.
- [ ] **Documents / PDF upload** — `src/components/dataset/pdf-upload-dialog.tsx`.
- [ ] **Automations** — `src/app/automations/`, `src/app/admin/automations/`, `src/components/automations/*`, `src/stores/automation-store.ts`, `src/lib/automation-utils.ts`, `@xyflow/react` dep.
- [ ] **Admin surfaces** — `src/app/admin/`, `src/components/admin/*` (unused in v1).
- [ ] **Notifications** — `src/components/notifications/*`, `src/stores/notification-store.ts` (optional; keep if cheap).
- [ ] **Firebase deploy config** — delete `firebase.json`, `.firebaserc` at repo root (not in this dir) — standardize on Vercel.
- [ ] **Auth surface shrink** — collapse `src/app/login/`, `src/app/register/`, `src/components/auth/*` into a single password-gate screen (see "Add" below).
- [ ] **Training admin** — any page/component hitting `/api/train` or `/api/admin/*`.

## Add (net-new for insightxpert.ai v1)

- [ ] **New chunk renderers** under `src/components/chunks/`:
  - `profile-loaded-chunk.tsx`
  - `schema-linking-chunk.tsx` (container)
  - `candidate-sqls-chunk.tsx`
  - `literals-chunk.tsx`
  - `semantic-matches-chunk.tsx`
  - `join-paths-chunk.tsx`
  - `linked-schema-final-chunk.tsx` (with column-source badges: `trial_sql | semantic | lsh | join_path`)
- [ ] **Extend `src/lib/chunk-parser.ts`** + `src/lib/sse-client.ts` to recognize the new chunk types.
- [ ] **"Profile this DB" action** in `src/components/layout/dataset-selector.tsx`.
- [ ] **SQL runner as right-side drawer** — check current render in `src/components/sql/sql-executor.tsx`; if modal, convert to a Sheet from `components/ui/sheet.tsx`. Upgrade editor from `react-syntax-highlighter` to Monaco (`@monaco-editor/react`) or CodeMirror.
- [ ] **Password-gate screen** — `src/app/unlock/page.tsx` (minimal). Middleware in `src/middleware.ts` redirects all routes to `/unlock` until signed cookie is present.

## Do not yet remove

- Keep `src/components/insights/*` — we likely use insights-lite in v1 for "save this answer" UX.
- Keep `src/components/sample-questions/*` — welcome screen seed questions.
- Keep `src/components/health/*` — FE readiness gate.

## After prune

- [ ] Run `pnpm install` (or `npm`, match `package.json` lockfile).
- [ ] `pnpm typecheck` — zero errors.
- [ ] `pnpm lint` — zero errors.
- [ ] `pnpm build` — succeeds.
- [ ] Commit the pruned state as the baseline for further work.
