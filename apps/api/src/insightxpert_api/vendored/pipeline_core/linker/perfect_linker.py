"""Build perfect schema linking from gold SQL queries.

Parses each gold SQL with sqlglot to extract the exact tables, columns, and
literals used, then adds FK join paths and renders a pruned schema — giving
the generator the *ideal* schema context for each question.

Usage (standalone):
    python -m insightxpert.linker.perfect_linker --benchmark mini_dev -o perfect_linking.json

The output JSON maps question text → pruned schema_text, and can be fed to
the pipeline via ``--perfect-linking perfect_linking.json``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.linker.linking_utils import add_join_paths, render_pruned_schema
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
from insightxpert_api.vendored.pipeline_core.profiler.profiler import Profiler

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)


def _parse_gold_sql(sql: str, dialect: str = "sqlite") -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """Parse a gold SQL query and extract tables, columns, and literals.

    Returns (tables, columns_as_(table,col), literals).
    Columns may have table="" if unqualified in the SQL.
    """
    tables: set[str] = set()
    columns: set[tuple[str, str]] = set()
    literals: set[str] = set()

    try:
        read_dialect = "snowflake" if dialect == "snowflake" else "sqlite"
        parsed = sqlglot.parse_one(sql, read=read_dialect)
    except sqlglot.errors.SqlglotError:
        logger.warning("sqlglot failed to parse gold SQL: %.120s", sql)
        return tables, columns, literals

    # Build alias map: alias_name -> real table name
    alias_map: dict[str, str] = {}
    for table_node in parsed.find_all(exp.Table):
        alias = table_node.alias
        if alias:
            alias_map[alias] = table_node.name

    # Extract tables
    tables = {t.name for t in parsed.find_all(exp.Table) if t.name}

    # Extract columns, resolving aliases
    for col in parsed.find_all(exp.Column):
        col_name = col.name
        if not col_name:
            continue
        table_ref = col.table or ""
        real_table = alias_map.get(table_ref, table_ref)
        columns.add((real_table, col_name))

    # Extract string literals
    literals = {
        lit.this for lit in parsed.find_all(exp.Literal) if lit.is_string and lit.this
    }

    return tables, columns, literals


def _resolve_unqualified_columns(
    columns: set[tuple[str, str]],
    schema: DatabaseSchema,
) -> set[tuple[str, str]]:
    """Resolve ("", col_name) entries against the schema (high-recall).

    Uses case-insensitive matching: gold SQL may use different casing than
    the schema (e.g. ``FastestLapTime`` vs ``fastestLapTime``).  Resolved
    entries always use the *schema's* canonical casing so downstream lookups
    work correctly.
    """
    # Map lowercase col name → list of (real_table_name, real_col_name)
    col_to_tables: dict[str, list[tuple[str, str]]] = {}
    for t in schema.tables:
        for c in t.columns:
            col_to_tables.setdefault(c.name.lower(), []).append((t.name, c.name))

    # Also build lowercase table name → real table name
    table_canon: dict[str, str] = {t.name.lower(): t.name for t in schema.tables}

    resolved: set[tuple[str, str]] = set()
    for table_ref, col_name in columns:
        if table_ref:
            # Resolve table name to canonical casing
            canon_table = table_canon.get(table_ref.lower(), table_ref)
            # Resolve column name to canonical casing for that table
            matches = col_to_tables.get(col_name.lower(), [])
            canon_col = col_name
            for tname, cname in matches:
                if tname.lower() == canon_table.lower():
                    canon_col = cname
                    break
            resolved.add((canon_table, canon_col))
        else:
            for tname, cname in col_to_tables.get(col_name.lower(), []):
                resolved.add((tname, cname))
    return resolved


def _load_bird_meta(db_id: str, benchmark: str) -> "BirdMetadata | None":
    """Load BIRD CSV metadata for a database (if available)."""
    try:
        from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata
        meta = BirdMetadata.load(db_id, benchmark=benchmark)
        return meta
    except Exception:
        return None


def build_perfect_columns(
    gold_sql: str,
    schema: DatabaseSchema,
    normalize_case: bool = False,
    use_bridge: bool = False,
    join_graph: "JoinGraph | None" = None,
    dialect: str = "sqlite",
) -> tuple[set[str], set[tuple[str, str]]]:
    """Parse gold SQL and derive the canonical ``(tables, columns)`` used in the perfect schema.

    This is the structured half of ``build_perfect_schema``: it stops after
    join-path expansion and before rendering, so callers (e.g. the few-shot
    augmentation path) can union additional columns in before rendering.
    """
    tables, columns, _ = _parse_gold_sql(gold_sql, dialect=dialect)

    if normalize_case:
        tables = {t.lower() for t in tables}
        columns = {(t.lower(), c.lower()) for t, c in columns}

    columns = _resolve_unqualified_columns(columns, schema)

    for table_ref, _ in columns:
        if table_ref:
            tables.add(table_ref)

    tables, columns = add_join_paths(
        tables, columns, schema,
        use_bridge=use_bridge,
        join_graph=join_graph,
    )
    return tables, columns


def build_perfect_schema(
    gold_sql: str,
    db_id: str,
    schema: DatabaseSchema,
    profile: "Profiler",
    bird_meta: "BirdMetadata | None" = None,
    normalize_case: bool = False,
    use_bridge: bool = False,
    join_graph: "JoinGraph | None" = None,
    dialect: str = "sqlite",
) -> tuple[str, set[str], set[tuple[str, str]]]:
    """Build perfect pruned schema for a single question's gold SQL.

    Returns ``(schema_text, tables, columns)``. Tables/columns are exposed so
    callers can re-render with an augmented column set (e.g. when unioning
    few-shot example columns in).
    """
    tables, columns = build_perfect_columns(
        gold_sql=gold_sql,
        schema=schema,
        normalize_case=normalize_case,
        use_bridge=use_bridge,
        join_graph=join_graph,
        dialect=dialect,
    )

    schema_text = render_pruned_schema(tables, columns, schema, profile, bird_meta, join_graph)

    if not schema_text.strip():
        logger.warning(
            "Perfect linking produced empty schema for db=%s sql=%.80s; "
            "gold SQL may reference tables/columns not in schema",
            db_id, gold_sql,
        )

    return schema_text, tables, columns


def build_perfect_linking(
    benchmark: str = "mini_dev",
    db_id: str | None = None,
    evidence_backed: bool = False,
    dialect: str = "sqlite",
) -> dict[str, dict[str, str]]:
    """Build perfect linking for all test cases in a benchmark.

    Args:
        evidence_backed: If True, use evidence-enhanced profiles for richer
            column descriptions in the pruned schema.

    Returns a dict mapping question_id (str) → {question, db_id, difficulty, schema_text}.
    """
    from insightxpert_api.vendored.pipeline_core.evaluation.loader import load_test_cases

    cases = load_test_cases(
        test_file=settings.get_test_file(benchmark),
        db_id=db_id,
        db_dir=settings.get_db_dir(benchmark),
        benchmark=benchmark,
    )
    logger.info("Building perfect linking for %d test cases", len(cases))

    # Cache schemas and profiles per db_id
    schema_cache: dict[str, DatabaseSchema] = {}
    profile_cache: dict[str, object] = {}
    bird_meta_cache: dict[str, "BirdMetadata | None"] = {}
    join_graph_cache: dict[str, object] = {}  # JoinGraph | None

    result: dict[str, dict[str, str]] = {}
    failed = 0

    for case in cases:
        # Load schema if not cached
        if case.db_id not in schema_cache:
            profiles_dir = settings.get_profiles_dir(benchmark)
            schema_path = profiles_dir / case.db_id / "schema.json"
            # Fall back to mini_dev profiles when bird_dev profiles are missing
            # (same 11 databases, identical schemas).
            fallback_benchmark = benchmark
            if not schema_path.exists() and benchmark == "bird_dev":
                fallback_dir = settings.get_profiles_dir("mini_dev")
                fallback_path = fallback_dir / case.db_id / "schema.json"
                if fallback_path.exists():
                    schema_path = fallback_path
                    fallback_benchmark = "mini_dev"
                    logger.debug(
                        "Using mini_dev profile for %s (bird_dev profile missing)",
                        case.db_id,
                    )
            if not schema_path.exists():
                logger.error("Schema not found for %s at %s", case.db_id, schema_path)
                failed += 1
                continue
            schema_cache[case.db_id] = DatabaseSchema.model_validate_json(
                schema_path.read_text()
            )
            profile_cache[case.db_id] = Profiler.load_profile(
                case.db_id, evidence_backed=evidence_backed, benchmark=fallback_benchmark
            )
            bird_meta_cache[case.db_id] = _load_bird_meta(case.db_id, fallback_benchmark)
            try:
                join_graph_cache[case.db_id] = Profiler.load_join_graph(
                    case.db_id, benchmark=fallback_benchmark
                )
            except (FileNotFoundError, ValueError) as exc:
                logger.warning(
                    "No usable join_graph for %s: %s — hubs will be omitted",
                    case.db_id, exc,
                )
                join_graph_cache[case.db_id] = None

        schema = schema_cache[case.db_id]
        profile = profile_cache[case.db_id]
        bird_meta = bird_meta_cache[case.db_id]
        join_graph = join_graph_cache[case.db_id]

        try:
            schema_text, tables, columns = build_perfect_schema(
                gold_sql=case.gold_sql,
                db_id=case.db_id,
                schema=schema,
                profile=profile,
                bird_meta=bird_meta,
                join_graph=join_graph,
                dialect=dialect,
            )
            result[str(case.question_id)] = {
                "question_id": case.question_id,
                "question": case.question,
                "evidence": case.evidence,
                "db_id": case.db_id,
                "difficulty": case.difficulty,
                "schema_text": schema_text,
                "tables": sorted(tables),
                "columns": sorted([list(c) for c in columns]),
            }
        except Exception as e:
            logger.error(
                "Perfect linking failed for q%d (%s): %s",
                case.question_id, case.db_id, e,
            )
            failed += 1

    logger.info(
        "Perfect linking complete: %d/%d succeeded, %d failed",
        len(result), len(cases), failed,
    )
    return result


def main() -> None:
    """CLI entry point: build perfect linking JSON file."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Build perfect schema linking from gold SQL queries"
    )
    parser.add_argument(
        "--benchmark",
        choices=["bird_dev", "mini_dev"],
        default="mini_dev",
        help="Benchmark to build perfect linking for (default: mini_dev)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Optional: restrict to a single database ID",
    )
    parser.add_argument(
        "--evidence-backed",
        action="store_true",
        dest="evidence_backed",
        help="Use evidence-enhanced profiles for richer column descriptions",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output JSON file path (auto-named if not specified)",
    )
    args = parser.parse_args()

    if args.output is None:
        suffix = "_evidence" if args.evidence_backed else ""
        args.output = f"perfect_linking/perfect_linking_{args.benchmark}{suffix}.json"

    linking = build_perfect_linking(
        benchmark=args.benchmark, db_id=args.db, evidence_backed=args.evidence_backed
    )

    out_path = Path(args.output)
    with open(out_path, "w") as f:
        json.dump(linking, f, indent=2)

    print(f"Wrote {len(linking)} perfect schemas to {out_path}")


if __name__ == "__main__":
    main()
