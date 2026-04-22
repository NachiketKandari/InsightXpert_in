"""Profiling upgrade — batched summary/quirk generators + SSE streaming runner.

This package sits alongside the vendored pipeline_core profiler. The vendored
tree is read-only; we wrap it here with:

  * ``batched_summary.BatchedSummaryGenerator`` — 1 LLM call per batch of N
    columns, instead of the vendored 2-calls-per-column path.
  * ``batched_quirks.BatchedQuirkDetector`` — same shape, for quirks.
  * ``runner.run_profile_stream`` — bridges structlog + stage events to the
    existing ``EventEmitter`` SSE pipe.

See ``docs/superpowers/plans/2026-04-22-profiling-upgrade.md``.
"""
