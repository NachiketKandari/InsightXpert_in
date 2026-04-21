"""CLI entry point: python -m insightxpert <subcommand>"""
import argparse
import logging
import sys

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.log import setup_logging

logger = logging.getLogger(__name__)


def cmd_extract_schema(args):
    """Extract and print the schema for a database as JSON."""
    from insightxpert_api.vendored.pipeline_core.db import open_db
    from insightxpert_api.vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor

    try:
        with open_db(args.db) as db:
            schema = SchemaExtractor().extract(db)
    except FileNotFoundError as e:
        logger.error("%s", e)
        sys.exit(1)

    print(schema.model_dump_json(indent=2))  # data output — intentional stdout


def cmd_load_tests(args):
    """Load and print test cases from dev.json, with optional filtering."""
    from insightxpert_api.vendored.pipeline_core.evaluation.loader import load_test_cases

    benchmark = getattr(args, "benchmark", "bird_dev")
    cases = load_test_cases(
        test_file=settings.get_test_file(benchmark),
        db_id=args.db,
        difficulty=args.difficulty,
        limit=args.limit,
        db_dir=settings.get_db_dir(benchmark),
        benchmark=benchmark,
    )
    logger.info("Loaded %d test cases", len(cases))
    for case in cases:
        print(case.model_dump_json())  # data output — intentional stdout


def cmd_test_llm(args):
    """Send a prompt to Gemini via the test_llm.j2 template and print the response."""
    from insightxpert_api.vendored.pipeline_core.llm.gemini import GeminiLLM

    if not settings.gemini_api_key or settings.gemini_api_key == "your_api_key_here":
        logger.error("GEMINI_API_KEY not set in .env")
        sys.exit(1)

    jinja_env = settings.get_jinja_env()
    template = jinja_env.get_template("test_llm.j2")
    prompt = template.render(prompt=args.prompt)

    llm = GeminiLLM(api_key=settings.gemini_api_key, model=settings.gemini_model)
    response = llm.generate(prompt)
    print(response)  # data output — intentional stdout


def cmd_prompt_run(args):
    """Send a pre-rendered prompt directly to the LLM and extract SQL from the response.

    Reads the full prompt from stdin. This bypasses the entire pipeline
    (profiling, linking, etc.) — useful for rapid prompt engineering when
    the prompt already contains the linked schema.
    """
    import json
    import re

    prompt = sys.stdin.read()
    if not prompt.strip():
        logger.error("No prompt provided on stdin")
        sys.exit(1)

    llm = _make_llm(
        model=getattr(args, "model", None),
        thinking_level=getattr(args, "thinking_level", None),
    )

    raw = llm.generate(prompt)

    # Extract SQL using the same logic as CandidateGenerator._extract_sql
    fence_re = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)
    match = fence_re.search(raw)
    if match:
        sql = match.group(1).strip()
    else:
        sql = raw.strip()
    sql = sql.rstrip(";").strip()
    if ";" in sql:
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt.upper().startswith("SELECT"):
                sql = stmt
                break

    result = {
        "sql": sql,
        "raw_response": raw,
        "input_tokens": llm.total_input_tokens,
        "output_tokens": llm.total_output_tokens,
    }
    print(json.dumps(result, indent=2))  # data output — intentional stdout


def _make_llm(model: str | None = None, thinking_level: str | None = None):
    """Validate API key config and return a GeminiLLM or ClaudeLLM instance.

    model and thinking_level override settings if provided (non-None).
    Dispatches to ClaudeLLM when model starts with "claude-".
    """
    resolved_model = model if model is not None else settings.gemini_model
    if resolved_model.startswith("claude-"):
        from insightxpert_api.vendored.pipeline_core.llm.claude import ClaudeLLM
        return ClaudeLLM(model=resolved_model)
    from insightxpert_api.vendored.pipeline_core.llm.gemini import GeminiLLM
    if not settings.gemini_api_key or settings.gemini_api_key == "your_api_key_here":
        logger.error("GEMINI_API_KEY not set in .env")
        sys.exit(1)
    return GeminiLLM(
        api_key=settings.gemini_api_key,
        model=resolved_model,
        thinking_level=thinking_level if thinking_level is not None else settings.gemini_thinking_level,
    )


def cmd_profile(args):
    """Run the offline profiling pipeline for one database or all databases."""
    import asyncio
    from insightxpert_api.vendored.pipeline_core.evaluation.loader import _available_db_ids
    from insightxpert_api.vendored.pipeline_core.profiler.profiler import Profiler

    benchmark = getattr(args, "benchmark", "bird_dev")
    llm = _make_llm()
    # Optional separate model for quirk enrichment (use a stronger model for better hints)
    quirk_model = getattr(args, "quirk_model", None)
    quirk_llm = _make_llm(model=quirk_model) if quirk_model else None
    profiler = Profiler(
        llm,
        quirk_llm=quirk_llm,
        containment_threshold=getattr(args, "containment_threshold", 0.9),
    )

    enrich_quirks = not getattr(args, "skip_quirks", False)

    async def _run():
        if args.all:
            db_dir = settings.get_db_dir(benchmark)
            db_ids = sorted(_available_db_ids(db_dir, benchmark))
            if not db_ids:
                logger.error("No databases found in %s", db_dir)
                sys.exit(1)
            logger.info("Profiling %d databases: %s", len(db_ids), ", ".join(db_ids))
            for db_id in db_ids:
                logger.info("=== %s ===", db_id)
                await profiler.profile_database(
                    db_id, with_evidence=args.with_evidence,
                    benchmark=benchmark, enrich_quirks=enrich_quirks,
                )
        else:
            if not args.db:
                logger.error("Provide --db <db_id> or --all")
                sys.exit(1)
            await profiler.profile_database(
                args.db, with_evidence=args.with_evidence,
                benchmark=benchmark, enrich_quirks=enrich_quirks,
            )

    asyncio.run(_run())


def cmd_show_profile(args):
    """Load and pretty-print a saved database profile as JSON."""
    from insightxpert_api.vendored.pipeline_core.profiler.profiler import Profiler
    profile = Profiler.load_profile(args.db)
    print(profile.model_dump_json(indent=2))  # data output — intentional stdout


def cmd_build_join_graph(args):
    """Build or rebuild join_graph.json for one or all profiled databases."""
    import pathlib

    from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
    from insightxpert_api.vendored.pipeline_core.profiler.join_graph_builder import build_join_graph

    benchmark = getattr(args, "benchmark", "bird_dev")
    profiles_base = settings.get_profiles_dir(benchmark)

    if getattr(args, "all", False):
        db_ids = sorted(
            d.name for d in profiles_base.iterdir()
            if d.is_dir() and (d / "schema.json").exists()
        )
    elif args.db:
        db_ids = [args.db]
    else:
        logger.error("Specify --db <db_id> or --all")
        sys.exit(1)

    from insightxpert_api.vendored.pipeline_core.db import open_db
    containment_threshold = getattr(args, "containment_threshold", 0.9)

    for db_id in db_ids:
        schema_path = profiles_base / db_id / "schema.json"
        if not schema_path.exists():
            logger.error("No schema.json for '%s' — run 'profile --db %s' first.", db_id, db_id)
            continue
        schema = DatabaseSchema.model_validate_json(schema_path.read_text())
        try:
            with open_db(db_id, benchmark=benchmark) as db:
                jg = build_join_graph(schema, db, containment_threshold=containment_threshold)
        except Exception as e:  # noqa: BLE001 — per-db failure must not abort the batch
            logger.error("Failed to build join graph for '%s': %s", db_id, e)
            continue
        out = profiles_base / db_id / "join_graph.json"
        out.write_text(jg.model_dump_json(indent=2))
        n_declared = sum(1 for e in jg.edges if e.kind == "declared")
        n_verified = sum(1 for e in jg.edges if e.kind == "value_verified")
        n_rejected = sum(1 for e in jg.edges if e.kind == "rejected")
        logger.info(
            "%s: %d edges (%d declared, %d verified, %d rejected) → %s",
            db_id, len(jg.edges), n_declared, n_verified, n_rejected, out,
        )


def _resolve_evidence(db_id: str, per_question_evidence: str, use_unified: bool) -> str:
    """Return the evidence string to use, based on the --unified-evidence flag.

    --unified-evidence: load profiles/{db_id}/unified_evidence.txt, ignore per-question evidence.
    default:            use per-question evidence as-is.
    """
    if not use_unified:
        return per_question_evidence
    from insightxpert_api.vendored.pipeline_core.profiler.evidence_unifier import load_unified_evidence
    unified = load_unified_evidence(db_id)
    if not unified:
        logger.warning(
            "No unified evidence found for '%s'. "
            "Run: python -m insightxpert generate-unified-evidence --db %s",
            db_id, db_id,
        )
    return unified


def cmd_generate_unified_evidence(args):
    """Consolidate per-question evidence hints into a single database-level reference."""
    from insightxpert_api.vendored.pipeline_core.evaluation.loader import load_test_cases
    from insightxpert_api.vendored.pipeline_core.profiler.evidence_unifier import EvidenceUnifier
    from insightxpert_api.vendored.pipeline_core.profiler.profiler import Profiler
    from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

    cases = load_test_cases(
        test_file=settings.test_file,
        db_id=args.db,
        db_dir=settings.db_dir,
    )
    if not cases:
        logger.error("No test cases found for db_id='%s'", args.db)
        sys.exit(1)

    evidences = [c.evidence for c in cases]
    logger.info("Loaded %d evidence strings from %d cases", len(evidences), len(cases))

    schema_path = settings.profiles_dir / args.db / "schema.json"
    if not schema_path.exists():
        logger.error("No profile found for '%s'. Run: python -m insightxpert profile --db %s", args.db, args.db)
        sys.exit(1)

    schema = DatabaseSchema.model_validate_json(schema_path.read_text())
    profile = Profiler.load_profile(args.db)

    llm = _make_llm()
    result = EvidenceUnifier(llm).generate(args.db, evidences, schema, profile)
    print(result)  # data output — intentional stdout


def _resolve_linking_mode(args) -> str:
    """Resolve linking_mode from --linking-mode and deprecated --no-linking flags."""
    linking_mode = getattr(args, "linking_mode", "multi-variant")
    if getattr(args, "no_linking", False) and linking_mode == "multi-variant":
        # --no-linking is a deprecated alias for --linking-mode none
        linking_mode = "none"
    return linking_mode


def cmd_ask(args):
    """Answer a natural-language question against a profiled database."""
    from insightxpert_api.vendored.pipeline_core.pipeline import Pipeline

    # Apply prompt template overrides if provided
    prompt_dir = getattr(args, "prompt_dir", None)
    if prompt_dir:
        from pathlib import Path
        settings._prompt_override_dir = Path(prompt_dir)

    benchmark = getattr(args, "benchmark", "bird_dev")
    evidence = _resolve_evidence(args.db, args.evidence or "", args.unified_evidence)
    linking_mode = _resolve_linking_mode(args)

    llm = _make_llm(
        model=getattr(args, "model", None),
        thinking_level=getattr(args, "thinking_level", None),
    )
    pipeline = Pipeline(
        llm=llm,
        linking_mode=linking_mode,
        use_refinement=not args.no_refinement,
        max_refinement_iterations=args.max_refinement_iterations,
        evidence_profile=args.evidence_profile,
        benchmark=benchmark,
        metadata_mode=getattr(args, "metadata_mode", "profiling"),
        use_literal_revision=getattr(args, "literal_revision", False),
        num_candidates=getattr(args, "num_candidates", 1),
        use_construction_checks=getattr(args, "construction_checks", False),
        use_intent_classify=getattr(args, "intent_classify", False),
        use_self_correct=getattr(args, "self_correct", False),
        use_dual_schema=getattr(args, "dual_schema", False),
        use_bridge_join=getattr(args, "bridge_join", False),
        use_forward_linking=getattr(args, "forward_linking", False),
        use_pruning=getattr(args, "pruning", False),
        use_bird_enriched=getattr(args, "bird_enriched", False),
        use_quirks=not getattr(args, "no_quirks", False),
    )

    from insightxpert_api.vendored.pipeline_core.models.query import QueryRequest
    req = QueryRequest(question=args.question, db_id=args.db, evidence=evidence)
    try:
        response = pipeline.answer(req)
    except FileNotFoundError as e:
        logger.error("%s", e)
        sys.exit(1)

    if getattr(args, "json", False):
        print(response.model_dump_json(indent=2))  # full pipeline response
    else:
        print(response.result.model_dump_json(indent=2))  # data output — intentional stdout


def cmd_evaluate(args):
    """Run execution-match evaluation over test cases."""
    import pathlib
    from insightxpert_api.vendored.pipeline_core.evaluation.loader import load_test_cases
    from insightxpert_api.vendored.pipeline_core.pipeline import Pipeline

    # Apply prompt template overrides if provided
    prompt_dir = getattr(args, "prompt_dir", None)
    if prompt_dir:
        settings._prompt_override_dir = pathlib.Path(prompt_dir)

    benchmark = getattr(args, "benchmark", "bird_dev")
    metadata_mode = getattr(args, "metadata_mode", "profiling")

    cases = load_test_cases(
        test_file=settings.get_test_file(benchmark),
        db_id=args.db,
        difficulty=args.difficulty,
        limit=args.limit,
        db_dir=settings.get_db_dir(benchmark),
        question_ids=args.question_ids,
        benchmark=benchmark,
    )
    logger.info("Loaded %d test cases", len(cases))

    if args.no_evidence:
        cases = [c.model_copy(update={"evidence": ""}) for c in cases]
        logger.info("Evidence stripped from all cases (--no-evidence)")
    elif getattr(args, "unified_evidence", False):
        # Load unified evidence per db_id (supports multi-db runs)
        from insightxpert_api.vendored.pipeline_core.profiler.evidence_unifier import load_unified_evidence
        unified_cache: dict[str, str] = {}
        def _get_unified(db_id: str) -> str:
            if db_id not in unified_cache:
                unified_cache[db_id] = load_unified_evidence(db_id)
                if not unified_cache[db_id]:
                    logger.warning(
                        "No unified evidence for '%s'. Run generate-unified-evidence first.", db_id
                    )
            return unified_cache[db_id]
        cases = [c.model_copy(update={"evidence": _get_unified(c.db_id)}) for c in cases]
        logger.info("Unified evidence applied to all cases (--unified-evidence)")

    linking_mode = _resolve_linking_mode(args)

    # Derive a results directory from the run parameters so different
    # filter combinations don't clobber each other's checkpoints.
    bench_tag = "minidev" if benchmark == "mini_dev" else "bird"
    db_tag = f"{bench_tag}_{args.db or 'all'}"
    if args.difficulty:
        db_tag = f"{db_tag}_{args.difficulty}"
    if metadata_mode != "profiling":
        db_tag = f"{db_tag}_{metadata_mode}"
    if linking_mode == "none":
        db_tag = f"{db_tag}_nolink"
    elif linking_mode == "single-prompt":
        db_tag = f"{db_tag}_singlelink"
    elif linking_mode == "single-prompt-v2":
        db_tag = f"{db_tag}_singlelink_v2"
    elif linking_mode == "single-prompt-clean":
        db_tag = f"{db_tag}_singlelink_clean"
    if args.no_refinement:
        db_tag = f"{db_tag}_norefine"
    if args.no_evidence:
        db_tag = f"{db_tag}_noevidence"
    elif getattr(args, "unified_evidence", False):
        db_tag = f"{db_tag}_unified"
    if args.evidence_profile:
        db_tag = f"{db_tag}_evidenceprofile"
    if getattr(args, "bird_enriched", False):
        db_tag = f"{db_tag}_birdenriched"
    if getattr(args, "no_quirks", False):
        db_tag = f"{db_tag}_noquirks"
    if getattr(args, "literal_revision", False):
        db_tag = f"{db_tag}_litrev"
    num_cand = getattr(args, "num_candidates", 1)
    if num_cand > 1:
        db_tag = f"{db_tag}_{num_cand}cand"
    if getattr(args, "construction_checks", False):
        db_tag = f"{db_tag}_constchk"
    if getattr(args, "intent_classify", False):
        db_tag = f"{db_tag}_intent"
    if getattr(args, "self_correct", False):
        db_tag = f"{db_tag}_selfcorrect"
    if getattr(args, "dual_schema", False):
        db_tag = f"{db_tag}_dualschema"
    if getattr(args, "perfect_linking", False):
        db_tag = f"{db_tag}_perfectlink"
    if getattr(args, "bridge_join", False):
        db_tag = f"{db_tag}_bridgejoin"
    if getattr(args, "forward_linking", False):
        db_tag = f"{db_tag}_fwdlink"
    if getattr(args, "pruning", False):
        db_tag = f"{db_tag}_pruning"
    if getattr(args, "few_shot", False):
        db_tag = f"{db_tag}_fewshot"

    # Include model/thinking override in dir name so runs don't clobber each other
    model_override = getattr(args, "model", None)
    thinking_override = getattr(args, "thinking_level", None)
    effective_model = model_override or settings.gemini_model
    effective_thinking = thinking_override if thinking_override is not None else settings.gemini_thinking_level
    # Shorten model name for directory: strip "gemini-" prefix and replace dots/dashes
    model_slug = effective_model.replace("gemini-", "").replace("-", "_").replace(".", "_")
    db_tag = f"{db_tag}_{model_slug}"
    if effective_thinking:
        db_tag = f"{db_tag}_{effective_thinking}think"

    out_dir = pathlib.Path("results") / db_tag
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = out_dir / "checkpoint.jsonl"
    if not args.resume and checkpoint_path.exists():
        logger.info(
            "Found existing checkpoint (%s). Starting fresh — use --resume to continue from it.",
            checkpoint_path,
        )
        checkpoint_path.unlink()

    # --- Load reuse-linking cache if provided ---
    reuse_linking: dict[str, str] | None = None
    if getattr(args, "reuse_linking", None):
        reuse_path = pathlib.Path(args.reuse_linking)
        if not reuse_path.exists():
            logger.error("Reuse-linking file not found: %s", reuse_path)
            return
        import json as _json
        with open(reuse_path) as _f:
            prev_data = _json.load(_f)
        prev_results = prev_data.get("results", [])
        reuse_linking = {}
        for r in prev_results:
            prompt = r.get("prompt", "")
            q = r.get("question", "")
            if prompt and q:
                # Extract schema_text from the rendered prompt
                schema_start = prompt.find("== Database Schema ==")
                # Try both markers: current prompt uses "== Rules ==",
                # older prompts may have used "== Universal SQLite Formulation Rules =="
                schema_end = prompt.find("== Rules ==")
                if schema_end == -1:
                    schema_end = prompt.find("== Universal SQLite Formulation Rules ==")
                if schema_end == -1:
                    schema_end = prompt.find("== Evidence ==")
                if schema_start != -1 and schema_end != -1:
                    schema_text = prompt[schema_start:schema_end].strip()
                    # Remove the header line
                    schema_text = schema_text.replace("== Database Schema ==", "").strip()
                    reuse_linking[q] = schema_text
        logger.info("Loaded %d linked schemas from %s (reuse-linking mode)", len(reuse_linking), reuse_path)

    # --- Build or load perfect linking if requested ---
    perfect_linking_data: dict | None = None
    if getattr(args, "perfect_linking", False) and reuse_linking is None:
        import json as _json
        from insightxpert_api.vendored.pipeline_core.linker.perfect_linker import build_perfect_linking

        # Always build the full benchmark cache (all DBs) so partial --db runs
        # don't create incomplete caches that later look "complete".
        # Use evidence-enhanced variant when --evidence-profile is also set.
        evidence_backed = getattr(args, "evidence_profile", False)
        suffix = "_evidence" if evidence_backed else ""
        full_cache_path = pathlib.Path(f"perfect_linking/perfect_linking_{benchmark}{suffix}.json")
        perfect_data = None
        if full_cache_path.exists():
            with open(full_cache_path) as _f:
                perfect_data = _json.load(_f)
            # Rebuild if cache is from the pre-few-shot format (missing tables/columns)
            # and few-shot augmentation is requested.
            needs_rebuild = (
                getattr(args, "few_shot", False)
                and perfect_data
                and not all("tables" in e and "columns" in e for e in perfect_data.values())
            )
            if needs_rebuild:
                logger.info(
                    "Perfect-linking cache %s lacks tables/columns for few-shot augmentation — rebuilding.",
                    full_cache_path,
                )
                perfect_data = None
            else:
                logger.info("Loaded %d perfect schemas from cache %s", len(perfect_data), full_cache_path)
        if perfect_data is None:
            full_cache_path.parent.mkdir(parents=True, exist_ok=True)
            perfect_data = build_perfect_linking(
                benchmark=benchmark, db_id=None, evidence_backed=evidence_backed
            )
            with open(full_cache_path, "w") as _f:
                _json.dump(perfect_data, _f, indent=2)
            logger.info("Built and cached %d perfect schemas to %s", len(perfect_data), full_cache_path)
        # Convert {qid: {question, schema_text, ...}} → {question: schema_text}
        reuse_linking = {
            entry["question"]: entry["schema_text"]
            for entry in perfect_data.values()
        }
        # Full metadata only needed when few-shot augments the perfect schema.
        if getattr(args, "few_shot", False):
            perfect_linking_data = perfect_data

    llm = _make_llm(
        model=model_override,
        thinking_level=thinking_override,
    )
    pipeline = Pipeline(
        llm=llm,
        linking_mode=linking_mode,
        use_refinement=not args.no_refinement,
        max_refinement_iterations=args.max_refinement_iterations,
        evidence_profile=args.evidence_profile,
        benchmark=benchmark,
        metadata_mode=metadata_mode,
        use_literal_revision=getattr(args, "literal_revision", False),
        num_candidates=getattr(args, "num_candidates", 1),
        use_construction_checks=getattr(args, "construction_checks", False),
        reuse_linking=reuse_linking,
        perfect_linking_data=perfect_linking_data,
        use_intent_classify=getattr(args, "intent_classify", False),
        use_self_correct=getattr(args, "self_correct", False),
        use_dual_schema=getattr(args, "dual_schema", False),
        use_bridge_join=getattr(args, "bridge_join", False),
        use_forward_linking=getattr(args, "forward_linking", False),
        use_pruning=getattr(args, "pruning", False),
        use_bird_enriched=getattr(args, "bird_enriched", False),
        use_quirks=not getattr(args, "no_quirks", False),
        use_few_shot=getattr(args, "few_shot", False),
    )

    max_concurrent = getattr(args, "max_concurrent", 1)
    timeout_secs = getattr(args, "timeout", 7200)

    def _timeout_handler(signum: int, frame: object) -> None:
        logger.error(
            "Evaluation timed out after %d seconds. Progress saved to %s. "
            "Run again with --resume to continue.",
            timeout_secs, checkpoint_path,
        )
        sys.exit(2)

    if timeout_secs > 0:
        import signal
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_secs)
        logger.info("Evaluation timeout set to %d seconds (%d minutes)", timeout_secs, timeout_secs // 60)

    try:
        if max_concurrent > 1:
            import asyncio as _asyncio
            logger.info("Running evaluation with max_concurrent=%d", max_concurrent)
            report = _asyncio.run(
                pipeline.async_evaluate(cases, checkpoint_path=checkpoint_path, max_concurrent=max_concurrent)
            )
        else:
            report = pipeline.evaluate(cases, checkpoint_path=checkpoint_path)
    except KeyboardInterrupt:
        logger.warning(
            "Interrupted. Progress saved to %s. Run again with --resume to continue.", checkpoint_path
        )
        sys.exit(1)
    finally:
        if timeout_secs > 0:
            signal.alarm(0)  # cancel the alarm

    # Attach run configuration to the report for traceability
    from insightxpert_api.vendored.pipeline_core.models.evaluation import RunConfig
    report.run_config = RunConfig(
        model=effective_model,
        thinking_level=effective_thinking or "",
        metadata_mode=metadata_mode,
        use_linking=linking_mode != "none",
        linking_mode=linking_mode,
        use_refinement=not args.no_refinement,
        use_evidence=not args.no_evidence,
        use_literal_revision=getattr(args, "literal_revision", False),
        num_candidates=getattr(args, "num_candidates", 1),
        use_construction_checks=getattr(args, "construction_checks", False),
        use_intent_classify=getattr(args, "intent_classify", False),
        use_self_correct=getattr(args, "self_correct", False),
        use_dual_schema=getattr(args, "dual_schema", False),
        use_perfect_linking=getattr(args, "perfect_linking", False),
        use_bridge_join=getattr(args, "bridge_join", False),
        use_forward_linking=getattr(args, "forward_linking", False),
        use_pruning=getattr(args, "pruning", False),
        use_bird_enriched=getattr(args, "bird_enriched", False),
        use_quirks=not getattr(args, "no_quirks", False),
        use_few_shot=getattr(args, "few_shot", False),
        benchmark=benchmark,
    )
    logger.info(
        "Run config: model=%s thinking=%s metadata=%s linking=%s refinement=%s evidence=%s",
        effective_model, effective_thinking or "default", metadata_mode,
        linking_mode, not args.no_refinement, not args.no_evidence,
    )

    # Write final report (JSON)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"eval_results_{ts}.json"
    out_file.write_text(report.model_dump_json(indent=2))
    logger.info("Results saved to %s", out_file)

    # Write CSV
    import csv
    csv_file = out_dir / f"eval_results_{ts}.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "question_id", "question", "hint", "hint_given",
            "prompt", "gold_sql", "predicted_sql", "evaluation",
        ])
        for r in report.results:
            writer.writerow([
                r.question_id,
                r.question,
                r.evidence,
                "true" if r.evidence else "false",
                r.prompt,
                r.gold_sql,
                r.predicted_sql,
                "correct" if r.execution_match else "wrong",
            ])
    logger.info("CSV saved to %s", csv_file)

    # Rename log file to include outcome: N{total}_acc{pct}pct
    from insightxpert_api.vendored.pipeline_core.log import current_log_file, rename_log
    old_log = current_log_file()
    if old_log and old_log.exists():
        acc_pct = round(report.accuracy * 100)
        # stem is like "evaluate-toxicology-nolink_20260401_001653"
        # split off the two trailing timestamp parts and insert outcome in the middle
        stem_parts = old_log.stem.rsplit("_", 2)
        if len(stem_parts) == 3:
            new_stem = f"{stem_parts[0]}_N{report.total}_acc{acc_pct}pct_{stem_parts[1]}_{stem_parts[2]}"
        else:
            new_stem = f"{old_log.stem}_N{report.total}_acc{acc_pct}pct"
        rename_log(old_log.parent / f"{new_stem}.log")

    # Clean up checkpoint on successful completion
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.debug("Checkpoint cleared")


def cmd_build_few_shot(args):
    """Sample BIRD train QA pairs per DB, embed them, and persist for retrieval."""
    from pathlib import Path
    from insightxpert_api.vendored.pipeline_core.few_shot.embedder import build_index

    bird_train = Path(args.bird_train)
    if not bird_train.exists():
        logger.error(
            "BIRD train file not found at %s. Download it from "
            "https://bird-bench.github.io/ and pass --bird-train PATH.",
            bird_train,
        )
        sys.exit(1)

    benchmark = getattr(args, "benchmark", "mini_dev")
    llm = _make_llm()  # uses default Gemini model; embedding uses gemini-embedding-001
    pairs_path, emb_path = build_index(
        bird_train_path=bird_train,
        llm=llm,
        benchmark=benchmark,
        per_db=args.per_db,
        seed=args.seed,
    )
    logger.info("Done. Pairs=%s embeddings=%s", pairs_path, emb_path)


def cmd_failed_ids(args):
    """Extract question IDs that failed (execution_match=false) from an eval results JSON."""
    import json
    from pathlib import Path

    path = Path(args.results_file)
    if not path.exists():
        logger.error("File not found: %s", path)
        sys.exit(1)

    with path.open() as f:
        report = json.load(f)

    failed = [
        r["question_id"]
        for r in report.get("results", [])
        if not r.get("execution_match", True)
        and (args.db is None or r.get("db_id") == args.db)
        and (args.difficulty is None or r.get("difficulty") == args.difficulty)
    ]

    if not failed:
        logger.info("No failures found matching the given filters.")
        return

    logger.info("Found %d failed question(s)", len(failed))

    fmt = args.format
    if fmt == "json":
        import json as _json
        print(_json.dumps(failed))
    elif fmt == "lines":
        for qid in failed:
            print(qid)
    else:  # default: space-separated (for shell $() substitution)
        print(" ".join(str(q) for q in failed))


def cmd_compare(args):
    """Compare evaluation result files: two files, one-vs-all, or all pairs."""
    import json as _json
    from pathlib import Path
    from insightxpert_api.vendored.pipeline_core.evaluation.comparator import (
        compare_matrix,
        compare_reports,
        discover_result_files,
        format_comparison_text,
        format_matrix_text,
    )

    # Mode 1: explicit two files
    if args.file_a and args.file_b:
        path_a = Path(args.file_a)
        path_b = Path(args.file_b)
        for p in (path_a, path_b):
            if not p.exists():
                logger.error("File not found: %s", p)
                sys.exit(1)
        comp = compare_reports(path_a, path_b)
        if args.json:
            print(_json.dumps(comp, indent=2))
        else:
            print(format_comparison_text(comp))
        return

    # Auto-discover runs
    results_dir = Path("results")
    prefix = args.prefix or "minidev_all_"
    files = discover_result_files(results_dir, prefix=prefix)
    if not files:
        logger.error("No result files found in %s with prefix '%s'", results_dir, prefix)
        sys.exit(1)
    logger.info("Discovered %d runs: %s", len(files), ", ".join(f.parent.name for f in files))

    # Mode 2: --against <file> vs all discovered runs
    target = Path(args.against) if args.against else None
    if target and not target.exists():
        logger.error("File not found: %s", target)
        sys.exit(1)

    comparisons = compare_matrix(files, target=target)

    if args.json:
        print(_json.dumps(comparisons, indent=2))
    else:
        print(format_matrix_text(comparisons))


def cmd_verify(args):
    """Check whether a predicted SQL matches the gold SQL for a specific question."""
    from insightxpert_api.vendored.pipeline_core.evaluation.executor import verify_candidate
    from insightxpert_api.vendored.pipeline_core.evaluation.loader import load_test_cases

    cases = load_test_cases(
        test_file=settings.test_file,
        db_id=args.db,
        db_dir=settings.db_dir,
        question_ids=[args.question_id],
    )
    if not cases:
        logger.error("Question ID %d not found (db_id=%s)", args.question_id, args.db or "any")
        sys.exit(1)

    case = cases[0]

    if args.predicted_sql:
        predicted_sql = args.predicted_sql
    else:
        # Run the pipeline to get predicted SQL
        from insightxpert_api.vendored.pipeline_core.pipeline import Pipeline
        llm = _make_llm()
        pipeline = Pipeline(
            llm=llm,
            use_linking=not args.no_linking,
            use_refinement=not args.no_refinement,
            max_refinement_iterations=args.max_refinement_iterations,
            evidence_profile=args.evidence_profile,
            use_literal_revision=getattr(args, "literal_revision", False),
            num_candidates=getattr(args, "num_candidates", 1),
            use_construction_checks=getattr(args, "construction_checks", False),
        )
        from insightxpert_api.vendored.pipeline_core.models.query import QueryRequest
        req = QueryRequest(question=case.question, db_id=case.db_id, evidence=case.evidence)
        try:
            response = pipeline.answer(req)
        except FileNotFoundError as e:
            logger.error("%s", e)
            sys.exit(1)
        # Use refined SQL if refinement ran and improved the result
        if response.refined and response.refined.iterations > 0:
            predicted_sql = response.refined.sql
        else:
            predicted_sql = response.candidate.sql if response.candidate else ""

    result = verify_candidate(
        db_id=case.db_id,
        predicted_sql=predicted_sql,
        gold_sql=case.gold_sql,
        question_id=case.question_id,
    )
    import json
    print(json.dumps({
        "question_id": result.question_id,
        "question": case.question,
        "is_correct": result.is_correct,
        "predicted_sql": result.predicted_sql,
        "gold_sql": result.gold_sql,
        "predicted_rows": result.predicted_rows,
        "gold_rows": result.gold_rows,
        "error": result.error,
    }, indent=2))


def _add_benchmark_args(p) -> None:
    """Add --benchmark, --metadata-mode, --model, and --thinking-level to a subparser."""
    p.add_argument(
        "--benchmark",
        choices=["bird_dev", "mini_dev", "spider_snow"],
        default="bird_dev",
        help="Which benchmark to use: bird_dev (default) or mini_dev (500 SQLite questions)",
    )
    p.add_argument(
        "--metadata-mode",
        choices=["none", "bird", "profiling", "fused"],
        default="profiling",
        dest="metadata_mode",
        help=(
            "Column metadata injected into SQL generation prompts (default: profiling). "
            "none=raw schema only, bird=BIRD CSV descriptions, "
            "profiling=LLM summaries, fused=both"
        ),
    )
    p.add_argument(
        "--model",
        default=None,
        dest="model",
        help="Override the Gemini model (e.g. gemini-3-flash-preview). Defaults to GEMINI_MODEL in .env.",
    )
    p.add_argument(
        "--thinking-level",
        default=None,
        dest="thinking_level",
        choices=["none", "low", "medium", "high"],
        help="Override Gemini thinking level (none/low/medium/high). Defaults to GEMINI_THINKING_LEVEL in .env.",
    )


def _make_run_tag(args) -> str:
    """Build a human-readable run identifier from parsed CLI args for log file naming."""
    parts = [args.command]
    db = getattr(args, "db", None)
    if db:
        parts.append(db)
    elif getattr(args, "all", False):
        parts.append("all")
    if getattr(args, "difficulty", None):
        parts.append(args.difficulty)
    if getattr(args, "question_ids", None):
        parts.append("qids")
    linking_mode = getattr(args, "linking_mode", "multi-variant")
    if getattr(args, "no_linking", False) and linking_mode == "multi-variant":
        parts.append("nolink")
    elif linking_mode == "none":
        parts.append("nolink")
    elif linking_mode == "single-prompt":
        parts.append("singlelink")
    elif linking_mode == "single-prompt-v2":
        parts.append("singlelink_v2")
    elif linking_mode == "single-prompt-clean":
        parts.append("singlelink_clean")
    if getattr(args, "no_refinement", False):
        parts.append("norefine")
    if getattr(args, "no_evidence", False):
        parts.append("noevidence")
    elif getattr(args, "unified_evidence", False):
        parts.append("unified")
    if getattr(args, "evidence_profile", False):
        parts.append("evprofile")
    return "-".join(parts)


def main():
    parser = argparse.ArgumentParser(
        prog="insightxpert",
        description="InsightXpert Text-to-SQL CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # extract-schema
    p_schema = sub.add_parser("extract-schema", help="Extract DB schema as JSON")
    p_schema.add_argument("--db", required=True, help="Database ID (e.g. toxicology)")
    p_schema.set_defaults(func=cmd_extract_schema)

    # load-tests
    p_tests = sub.add_parser("load-tests", help="Load test cases from dev.json")
    p_tests.add_argument("--db", default=None, help="Filter by database ID")
    p_tests.add_argument(
        "--difficulty",
        choices=["simple", "moderate", "challenging"],
        default=None,
        help="Filter by difficulty",
    )
    p_tests.add_argument("--limit", type=int, default=None, help="Max number of cases")
    p_tests.add_argument("--benchmark", choices=["bird_dev", "mini_dev", "spider_snow"], default="bird_dev")
    p_tests.set_defaults(func=cmd_load_tests)

    # test-llm
    p_llm = sub.add_parser("test-llm", help="Send a prompt to Gemini")
    p_llm.add_argument("--prompt", required=True, help="Prompt text")
    p_llm.set_defaults(func=cmd_test_llm)

    # prompt-run
    p_prompt = sub.add_parser(
        "prompt-run",
        help="Send a pre-rendered prompt (from stdin) to the LLM and extract SQL",
    )
    p_prompt.add_argument(
        "--model", default=None,
        help="Override Gemini model (defaults to GEMINI_MODEL in .env)",
    )
    p_prompt.add_argument(
        "--thinking-level", default=None, dest="thinking_level",
        choices=["none", "low", "medium", "high"],
        help="Override Gemini thinking level",
    )
    p_prompt.set_defaults(func=cmd_prompt_run)

    # profile
    p_prof = sub.add_parser("profile", help="Profile a database (offline, run once)")
    grp = p_prof.add_mutually_exclusive_group()
    grp.add_argument("--db", default=None, help="Database ID to profile")
    grp.add_argument("--all", action="store_true", help="Profile all databases")
    p_prof.add_argument("--benchmark", choices=["bird_dev", "mini_dev", "spider_snow"], default="bird_dev",
                        help="Which benchmark's databases to profile")
    p_prof.add_argument(
        "--with-evidence",
        action="store_true",
        dest="with_evidence",
        help=(
            "Generate evidence-backed LLM summaries using domain hints from test cases. "
            "Saves profile + vector index to profiles/{db_id}/evidence/ "
            "(LSH index is shared with the normal profile)."
        ),
    )
    p_prof.add_argument(
        "--skip-quirks",
        action="store_true",
        dest="skip_quirks",
        help="Skip the quirk-enrichment step (disables cryptic column hints and enum labels).",
    )
    p_prof.add_argument(
        "--quirk-model",
        default=None,
        dest="quirk_model",
        help=(
            "Use a different model for quirk enrichment (e.g. 'gemini-3.1-pro-preview'). "
            "If unset, uses the same model as the rest of profiling. "
            "A stronger model here gives better semantic hints on cryptic columns."
        ),
    )
    p_prof.add_argument(
        "--containment-threshold",
        type=float,
        default=0.9,
        dest="containment_threshold",
        help=(
            "Min child-side value containment ratio for an implicit FK to be "
            "accepted as value_verified (default 0.9)."
        ),
    )
    p_prof.set_defaults(func=cmd_profile)

    # show-profile
    p_show = sub.add_parser("show-profile", help="Print a saved profile as JSON")
    p_show.add_argument("--db", required=True, help="Database ID")
    p_show.set_defaults(func=cmd_show_profile)

    # generate-unified-evidence
    p_ue = sub.add_parser(
        "generate-unified-evidence",
        help="Consolidate per-question evidence hints into a single database-level reference",
    )
    p_ue.add_argument("--db", required=True, help="Database ID")
    p_ue.set_defaults(func=cmd_generate_unified_evidence)

    # verify
    p_verify = sub.add_parser(
        "verify",
        help="Check whether a predicted SQL matches gold SQL for a specific question",
    )
    p_verify.add_argument("--db", default=None, help="Filter by database ID (optional)")
    p_verify.add_argument("--question-id", type=int, required=True, dest="question_id", help="Question ID to verify")
    p_verify.add_argument(
        "--predicted-sql",
        default=None,
        dest="predicted_sql",
        metavar="SQL",
        help="SQL to verify; if omitted, runs the pipeline to generate one",
    )
    p_verify.add_argument(
        "--no-linking",
        action="store_true",
        dest="no_linking",
        help="Disable schema linking when generating SQL (only used if --predicted-sql is omitted)",
    )
    p_verify.add_argument(
        "--evidence-profile",
        action="store_true",
        dest="evidence_profile",
        help="Use the evidence-backed profile and vector index (only used if --predicted-sql is omitted)",
    )
    p_verify.add_argument(
        "--no-refinement",
        action="store_true",
        dest="no_refinement",
        help="Disable SQL self-refinement (only used if --predicted-sql is omitted)",
    )
    p_verify.add_argument(
        "--max-refinement-iterations",
        type=int,
        default=2,
        dest="max_refinement_iterations",
        metavar="N",
        help="Max refinement iterations (default: 2)",
    )
    p_verify.set_defaults(func=cmd_verify)

    # ask
    p_ask = sub.add_parser("ask", help="Answer a question against a profiled database")
    p_ask.add_argument("--db", required=True, help="Database ID")
    p_ask.add_argument("--evidence", default="", help="Optional hint for the LLM")
    p_ask.add_argument(
        "--unified-evidence",
        action="store_true",
        dest="unified_evidence",
        help="Use the stored unified evidence for this database instead of --evidence",
    )
    p_ask.add_argument(
        "--linking-mode",
        choices=["multi-variant", "single-prompt", "single-prompt-v2", "single-prompt-clean", "none"],
        default="multi-variant",
        dest="linking_mode",
        help=(
            "Schema linking strategy: multi-variant (default, 5 separate LLM calls), "
            "single-prompt (1 LLM call for 5 candidate SQL queries), "
            "single-prompt-v2 (single-prompt with schema-grounded intent rephrasing), "
            "single-prompt-clean (1 LLM call, rules-free prompt — only schema + question), "
            "none (no linking, use full schema)"
        ),
    )
    p_ask.add_argument(
        "--no-linking",
        action="store_true",
        dest="no_linking",
        help="(Deprecated: use --linking-mode none) Disable schema linking",
    )
    p_ask.add_argument(
        "--evidence-profile",
        action="store_true",
        dest="evidence_profile",
        help="Use the evidence-backed profile and vector index (from profiles/{db_id}/evidence/)",
    )
    p_ask.add_argument(
        "--bird-enriched-profile",
        action="store_true",
        dest="bird_enriched",
        help="Use LLM-synthesized bird_enriched_summary per column (from profiles/{db_id}/bird_enriched/).",
    )
    p_ask.add_argument(
        "--no-quirks",
        action="store_true",
        dest="no_quirks",
        help="Disable the quirks render block for ablation.",
    )
    p_ask.add_argument(
        "--no-refinement",
        action="store_true",
        dest="no_refinement",
        help="Disable SQL self-refinement (Phase 5 feedback loop)",
    )
    p_ask.add_argument(
        "--max-refinement-iterations",
        type=int,
        default=2,
        dest="max_refinement_iterations",
        metavar="N",
        help="Max refinement iterations (default: 2)",
    )
    p_ask.add_argument(
        "--literal-revision",
        action="store_true",
        dest="literal_revision",
        help="Enable iterative literal-field revision during schema linking",
    )
    p_ask.add_argument(
        "--num-candidates",
        type=int,
        default=1,
        dest="num_candidates",
        metavar="N",
        help="Number of SQL candidates to generate (>1 enables majority voting, default: 1)",
    )
    p_ask.add_argument(
        "--construction-checks",
        action="store_true",
        dest="construction_checks",
        help="Enable SQL construction anti-pattern fixes (ORDER BY→MIN/MAX, concat→columns)",
    )
    p_ask.add_argument(
        "--intent-classify",
        action="store_true",
        dest="intent_classify",
        help="Enable intent-based rule selection for SQL generation prompts",
    )
    p_ask.add_argument(
        "--self-correct",
        action="store_true",
        dest="self_correct",
        help="Enable self-correction: LLM can execute SQL via tool call and iterate",
    )
    p_ask.add_argument(
        "--dual-schema",
        action="store_true",
        dest="dual_schema",
        help="Fallback to full schema SQL when linked schema SQL fails",
    )
    p_ask.add_argument(
        "--bridge-join",
        action="store_true",
        dest="bridge_join",
        help="Use BFS bridge discovery + MST join path pruning",
    )
    p_ask.add_argument(
        "--forward-linking",
        action="store_true",
        dest="forward_linking",
        help="Enable forward schema linking: LLM directly identifies relevant tables/columns before trial SQL",
    )
    p_ask.add_argument(
        "--pruning",
        action="store_true",
        dest="pruning",
        help="Enable LLM-based column pruning after schema linking (CHESS-style re-ranking)",
    )
    p_ask.add_argument("question", help="Natural language question")
    p_ask.add_argument(
        "--json",
        action="store_true",
        help="Output full QueryResponse JSON (includes reasoning, linked schema, refinement details)",
    )
    p_ask.add_argument(
        "--prompt-dir",
        dest="prompt_dir",
        default=None,
        help="Directory with .j2 template overrides (takes priority over default prompts/)",
    )
    _add_benchmark_args(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    # evaluate
    p_eval = sub.add_parser("evaluate", help="Run evaluation on test cases")
    p_eval.add_argument("--db", default=None, help="Filter by database ID")
    p_eval.add_argument(
        "--question-id",
        type=int,
        nargs="+",
        dest="question_ids",
        default=None,
        metavar="ID",
        help="Run only specific question ID(s) (e.g. --question-id 198 or --question-id 198 42 7)",
    )
    p_eval.add_argument("--limit", type=int, default=None, help="Max number of cases")
    p_eval.add_argument(
        "--difficulty",
        choices=["simple", "moderate", "challenging"],
        default=None,
    )
    p_eval.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint (skip already-evaluated questions)",
    )
    p_eval.add_argument(
        "--no-evidence",
        action="store_true",
        dest="no_evidence",
        help="Strip evidence from all test cases (ablation: measures accuracy without hints)",
    )
    p_eval.add_argument(
        "--unified-evidence",
        action="store_true",
        dest="unified_evidence",
        help="Replace per-question evidence with the stored unified evidence for each database",
    )
    p_eval.add_argument(
        "--linking-mode",
        choices=["multi-variant", "single-prompt", "single-prompt-v2", "single-prompt-clean", "none"],
        default="multi-variant",
        dest="linking_mode",
        help=(
            "Schema linking strategy: multi-variant (default, 5 separate LLM calls), "
            "single-prompt (1 LLM call for 5 candidate SQL queries), "
            "single-prompt-v2 (single-prompt with schema-grounded intent rephrasing), "
            "single-prompt-clean (1 LLM call, rules-free prompt — only schema + question), "
            "none (no linking, use full schema)"
        ),
    )
    p_eval.add_argument(
        "--no-linking",
        action="store_true",
        dest="no_linking",
        help="(Deprecated: use --linking-mode none) Disable schema linking",
    )
    p_eval.add_argument(
        "--evidence-profile",
        action="store_true",
        dest="evidence_profile",
        help="Use the evidence-backed profile and vector index (from profiles/{db_id}/evidence/)",
    )
    p_eval.add_argument(
        "--bird-enriched-profile",
        action="store_true",
        dest="bird_enriched",
        help=(
            "Use LLM-synthesized bird_enriched_summary per column "
            "(from profiles/{db_id}/bird_enriched/). Build first with "
            "scripts/build_bird_enriched_profiles.py."
        ),
    )
    p_eval.add_argument(
        "--no-quirks",
        action="store_true",
        dest="no_quirks",
        help="Disable the quirks render block (enum labels, aliases, type-mismatch notes) for ablation.",
    )
    p_eval.add_argument(
        "--no-refinement",
        action="store_true",
        dest="no_refinement",
        help="Disable SQL self-refinement (Phase 5 feedback loop)",
    )
    p_eval.add_argument(
        "--max-refinement-iterations",
        type=int,
        default=2,
        dest="max_refinement_iterations",
        metavar="N",
        help="Max refinement iterations (default: 2)",
    )
    p_eval.add_argument(
        "--literal-revision",
        action="store_true",
        dest="literal_revision",
        help="Enable iterative literal-field revision during schema linking",
    )
    p_eval.add_argument(
        "--num-candidates",
        type=int,
        default=1,
        dest="num_candidates",
        metavar="N",
        help="Number of SQL candidates to generate (>1 enables majority voting, default: 1)",
    )
    p_eval.add_argument(
        "--construction-checks",
        action="store_true",
        dest="construction_checks",
        help="Enable SQL construction anti-pattern fixes (ORDER BY→MIN/MAX, concat→columns)",
    )
    p_eval.add_argument(
        "--intent-classify",
        action="store_true",
        dest="intent_classify",
        help="Enable intent-based rule selection for SQL generation prompts",
    )
    p_eval.add_argument(
        "--self-correct",
        action="store_true",
        dest="self_correct",
        help="Enable self-correction: LLM can execute SQL via tool call and iterate",
    )
    p_eval.add_argument(
        "--dual-schema",
        action="store_true",
        dest="dual_schema",
        help="Fallback to full schema SQL when linked schema SQL fails",
    )
    p_eval.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        dest="max_concurrent",
        metavar="N",
        help="Max concurrent questions to evaluate in parallel (default: 1 = sequential)",
    )
    p_eval.add_argument(
        "--timeout",
        type=int,
        default=7200,
        metavar="SECONDS",
        help="Kill the evaluation run after this many seconds (default: 7200 = 2 hours). Set 0 to disable.",
    )
    p_eval.add_argument(
        "--reuse-linking",
        type=str,
        default=None,
        dest="reuse_linking",
        metavar="FILE",
        help="Reuse schema linking from a previous eval results JSON. Skips linking, only re-runs SQL generation.",
    )
    p_eval.add_argument(
        "--perfect-linking",
        action="store_true",
        dest="perfect_linking",
        help=(
            "Use perfect schema linking derived from gold SQL. "
            "Builds or loads a cached perfect_linking.json, bypassing the LLM linker. "
            "Useful for isolating SQL generation prompt issues from linking errors."
        ),
    )
    p_eval.add_argument(
        "--bridge-join",
        action="store_true",
        dest="bridge_join",
        help=(
            "Use BFS bridge discovery + MST join path pruning instead of "
            "unconditional PK/FK addition. Finds intermediate tables and "
            "only adds connectivity columns along minimum spanning tree edges."
        ),
    )
    p_eval.add_argument(
        "--forward-linking",
        action="store_true",
        dest="forward_linking",
        help="Enable forward schema linking: LLM directly identifies relevant tables/columns before trial SQL",
    )
    p_eval.add_argument(
        "--pruning",
        action="store_true",
        dest="pruning",
        help="Enable LLM-based column pruning after schema linking (CHESS-style re-ranking)",
    )
    p_eval.add_argument(
        "--few-shot",
        action="store_true",
        dest="few_shot",
        help=(
            "Retrieve a similar BIRD-train question and inject it (with its gold SQL) "
            "into the SQL-gen prompt; also unions the example's gold-SQL columns into "
            "the linked schema. Build the index first with: "
            "python -m insightxpert build-few-shot --bird-train PATH --benchmark mini_dev"
        ),
    )
    p_eval.add_argument(
        "--prompt-dir",
        dest="prompt_dir",
        default=None,
        help="Directory with .j2 template overrides (takes priority over default prompts/)",
    )
    _add_benchmark_args(p_eval)
    p_eval.set_defaults(func=cmd_evaluate)

    # build-join-graph
    p_jg = sub.add_parser(
        "build-join-graph",
        help="Build join_graph.json (declared + implicit FK edges) for profiled databases",
    )
    jg_grp = p_jg.add_mutually_exclusive_group()
    jg_grp.add_argument("--db", default=None, help="Database ID to build graph for")
    jg_grp.add_argument("--all", action="store_true", help="Build for all profiled databases")
    p_jg.add_argument(
        "--benchmark",
        choices=["bird_dev", "mini_dev", "spider_snow"],
        default="bird_dev",
        help="Benchmark to use (default: bird_dev)",
    )
    p_jg.add_argument(
        "--containment-threshold",
        type=float,
        default=0.9,
        dest="containment_threshold",
        help=(
            "Min child-side value containment ratio for an implicit FK to be "
            "accepted as value_verified (default 0.9). Below this, the candidate "
            "is recorded as rejected(low_containment)."
        ),
    )
    p_jg.set_defaults(func=cmd_build_join_graph)

    # build-few-shot
    p_fs = sub.add_parser(
        "build-few-shot",
        help="Sample BIRD train QA pairs per DB, embed them, and persist for runtime retrieval.",
    )
    p_fs.add_argument(
        "--bird-train", required=True, dest="bird_train",
        help="Path to BIRD train.json (the official training split).",
    )
    p_fs.add_argument(
        "--benchmark", choices=["bird_dev", "mini_dev", "spider_snow"],
        default="mini_dev",
        help="Benchmark whose DBs and questions define the filter (default: mini_dev).",
    )
    p_fs.add_argument(
        "--per-db", type=int, default=20, dest="per_db",
        help="QA pairs to sample per DB (default: 20).",
    )
    p_fs.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for reproducible sampling (default: 42).",
    )
    p_fs.set_defaults(func=cmd_build_few_shot)

    # failed-ids
    p_failed = sub.add_parser(
        "failed-ids",
        help="List question IDs that failed in a previous eval run (execution_match=false)",
    )
    p_failed.add_argument(
        "results_file",
        help="Path to eval_results_*.json file",
    )
    p_failed.add_argument("--db", default=None, help="Filter by database ID")
    p_failed.add_argument(
        "--difficulty",
        choices=["simple", "moderate", "challenging"],
        default=None,
        help="Filter by difficulty",
    )
    p_failed.add_argument(
        "--format",
        choices=["space", "json", "lines"],
        default="space",
        help="Output format: space-separated (default), JSON array, or one per line",
    )
    p_failed.set_defaults(func=cmd_failed_ids)

    # compare
    p_compare = sub.add_parser(
        "compare",
        help="Compare evaluation result files (two files, one-vs-all, or all pairs)",
    )
    p_compare.add_argument(
        "file_a", nargs="?", default=None,
        help="Path to first eval_results_*.json (required for two-file mode)",
    )
    p_compare.add_argument(
        "file_b", nargs="?", default=None,
        help="Path to second eval_results_*.json (required for two-file mode)",
    )
    p_compare.add_argument(
        "--against",
        default=None,
        metavar="FILE",
        help="Compare this file against all discovered runs (one-vs-many mode)",
    )
    p_compare.add_argument(
        "--prefix",
        default=None,
        metavar="PREFIX",
        help=(
            "Directory name prefix to filter discovered runs (default: 'minidev_all_'). "
            "Used with --against or when no positional files are given."
        ),
    )
    p_compare.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable text",
    )
    p_compare.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    setup_logging(tag=_make_run_tag(args))
    args.func(args)


if __name__ == "__main__":
    main()
