# Vendored patches

Patches applied on top of the verbatim vendored tree at
`apps/api/src/insightxpert_api/vendored/agents_core/`.

**Why:** the public tree is read-only vendored code. Anything we must diverge
on lands here and is re-applied on every re-sync by
`apps/api/scripts/apply-vendored-patches.sh`.

## Workflow

1. Re-sync `vendored/agents_core/` by copying the latest public files (see
   the top-level orchestration restoration plan for exact paths).
2. Run `./scripts/apply-vendored-patches.sh` from `apps/api/`. Already-applied
   patches skip cleanly thanks to `patch -N`.
3. If a new divergence is required, create a new numbered patch via
   `diff -u original new > scripts/vendored_patches/NNNN-description.patch`
   and add an entry below.

## Patches

- `0001-strip-org-id-from-toolcontext.patch` — our product is single-org; the
  `ToolContext.org_id` dataclass field is removed and every
  `ToolContext(org_id=...)` construction + every `context.org_id` reader
  is dropped. Call sites that thread `org_id` through function signatures
  (e.g. `analyst_loop`, `quant_analyst_loop`, `orchestrator_loop`) are left
  untouched; they become dead parameters we simply don't pass.
- `0002-drop-run-python-tool.patch` — removes `RunPythonTool` (weak
  `exec()` sandbox; deferred per `docs/deferred-features.md`). Also removes
  the associated helpers `_ALLOWED_IMPORT_ROOTS`, `_import_hook`, `_timeout`
  in `stat_tools.py` and the registration of `RunPythonTool()` in
  `quant_analyst._quant_registry`.
- `0003-inject-analyst-impl.patch` — makes the analyst implementation
  injectable. `orchestrator_loop` accepts an optional `analyst_impl` kwarg
  (defaults to the vendored analyst). The route layer passes
  `insightxpert_api.agents.analyst.analyst_loop` — our pipeline-wrapping
  adapter — so the vendored orchestrator drives our Phase A pipeline via a
  nominal async-generator contract. The kwarg is threaded down to
  `_run_sql_analyst` so enrichment sub-tasks use the same adapter.

## Applying by hand

From `apps/api/`:

```bash
patch -p0 -N -d src/insightxpert_api/vendored/agents_core \
  < scripts/vendored_patches/0001-strip-org-id-from-toolcontext.patch
```

The apply script does the same loop with idempotency + skip-on-conflict
handling.
