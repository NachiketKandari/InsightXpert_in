"""Sample QA pairs from BIRD train for the few-shot retrieval index.

Filters BIRD train.json to the databases we care about, drops any question
that overlaps with the eval benchmark, and pre-parses the gold SQL into
(table, column) pairs using the same logic as ``linker/perfect_linker.py``.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.linker.perfect_linker import _parse_gold_sql, _resolve_unqualified_columns
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)


@dataclass
class FewShotPair:
    """One sampled BIRD train QA pair, with its gold-SQL columns pre-resolved."""

    question: str
    gold_sql: str
    columns: list[tuple[str, str]] = field(default_factory=list)


def _load_bird_train(path: Path) -> list[dict]:
    """Load BIRD train.json. Accepts either a list at the root or {"data": [...]}."""
    with path.open() as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("data") or data.get("examples") or []
    if not isinstance(data, list):
        raise ValueError(f"Unexpected BIRD train format at {path}: not a list")
    return data


def _load_eval_questions(benchmark: str) -> set[str]:
    """Return case-folded question strings from the eval benchmark, for dedup."""
    test_file = settings.get_test_file(benchmark)
    with test_file.open() as f:
        cases = json.load(f)
    return {c.get("question", "").strip().casefold() for c in cases}


def _load_schema(db_id: str, benchmark: str) -> DatabaseSchema | None:
    """Load schema.json for db_id from the benchmark's profile dir."""
    schema_path = settings.get_profiles_dir(benchmark) / db_id / "schema.json"
    if not schema_path.exists():
        logger.warning(
            "No profile for db_id=%s at %s — pairs for this DB will skip column resolution",
            db_id, schema_path,
        )
        return None
    return DatabaseSchema.model_validate_json(schema_path.read_text())


def _resolve_columns(
    raw_columns: set[tuple[str, str]],
    schema: DatabaseSchema | None,
) -> list[tuple[str, str]]:
    """Resolve unqualified columns against the schema; return sorted list."""
    if schema is None:
        # Best-effort: keep only fully qualified pairs
        return sorted(rc for rc in raw_columns if rc[0])
    resolved = _resolve_unqualified_columns(raw_columns, schema)
    return sorted(resolved)


def sample_pairs(
    bird_train_path: Path,
    benchmark: str = "mini_dev",
    per_db: int = 20,
    seed: int = 42,
    db_ids: list[str] | None = None,
) -> dict[str, list[FewShotPair]]:
    """Sample ``per_db`` BIRD train QA pairs per benchmark DB.

    Args:
        bird_train_path: Path to BIRD's train.json.
        benchmark: Eval benchmark whose DBs and questions define the filter.
        per_db: Target sample size per DB (fewer if not enough eligible).
        seed: RNG seed for reproducible samples.
        db_ids: Optional explicit DB-id list; defaults to all DBs found in
            ``profiles/<benchmark>/``.

    Returns ``{db_id: [FewShotPair, ...]}``.
    """
    train = _load_bird_train(bird_train_path)
    logger.info("Loaded %d BIRD train entries from %s", len(train), bird_train_path)

    eval_questions = _load_eval_questions(benchmark)
    logger.info("Loaded %d eval questions for dedup (benchmark=%s)", len(eval_questions), benchmark)

    if db_ids is None:
        profiles_dir = settings.get_profiles_dir(benchmark)
        db_ids = sorted(d.name for d in profiles_dir.iterdir() if d.is_dir())
    target_dbs = set(db_ids)
    logger.info("Sampling for %d DBs: %s", len(target_dbs), ", ".join(sorted(target_dbs)))

    # Group by db_id, drop dedupe collisions
    by_db: dict[str, list[dict]] = {db: [] for db in target_dbs}
    skipped_dedupe = 0
    for entry in train:
        db_id = entry.get("db_id")
        if db_id not in target_dbs:
            continue
        question = (entry.get("question") or "").strip()
        sql = (entry.get("SQL") or entry.get("sql") or "").strip()
        if not question or not sql:
            continue
        if question.casefold() in eval_questions:
            skipped_dedupe += 1
            continue
        by_db[db_id].append({"question": question, "gold_sql": sql})

    if skipped_dedupe:
        logger.info("Dropped %d BIRD train entries that overlap with eval questions", skipped_dedupe)

    rng = random.Random(seed)
    result: dict[str, list[FewShotPair]] = {}
    for db_id in sorted(target_dbs):
        pool = by_db[db_id]
        if not pool:
            logger.warning("No BIRD train entries found for db_id=%s — skipping", db_id)
            result[db_id] = []
            continue

        sample = pool if len(pool) <= per_db else rng.sample(pool, per_db)
        if len(pool) < per_db:
            logger.warning(
                "db_id=%s: only %d eligible entries (requested %d) — taking all",
                db_id, len(pool), per_db,
            )

        schema = _load_schema(db_id, benchmark)
        pairs: list[FewShotPair] = []
        parse_failures = 0
        for entry in sample:
            try:
                _, raw_cols, _ = _parse_gold_sql(entry["gold_sql"])
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sqlglot parse failed for db_id=%s sql=%.80s: %s",
                    db_id, entry["gold_sql"], exc,
                )
                parse_failures += 1
                continue
            resolved = _resolve_columns(raw_cols, schema)
            pairs.append(
                FewShotPair(
                    question=entry["question"],
                    gold_sql=entry["gold_sql"],
                    columns=resolved,
                )
            )

        if parse_failures:
            logger.warning("db_id=%s: %d/%d gold SQL parse failures", db_id, parse_failures, len(sample))

        logger.info("db_id=%s: sampled %d pairs", db_id, len(pairs))
        result[db_id] = pairs

    total = sum(len(p) for p in result.values())
    logger.info("Sampling complete: %d pairs across %d DBs", total, len(result))
    return result


def serialize_pairs(pairs: dict[str, list[FewShotPair]]) -> dict[str, list[dict]]:
    """Convert pairs to a JSON-serializable dict."""
    return {
        db_id: [
            {
                "question": p.question,
                "gold_sql": p.gold_sql,
                "columns": [list(c) for c in p.columns],
            }
            for p in db_pairs
        ]
        for db_id, db_pairs in pairs.items()
    }


def deserialize_pairs(data: dict[str, list[dict]]) -> dict[str, list[FewShotPair]]:
    """Inverse of ``serialize_pairs``."""
    out: dict[str, list[FewShotPair]] = {}
    for db_id, items in data.items():
        out[db_id] = [
            FewShotPair(
                question=item["question"],
                gold_sql=item["gold_sql"],
                columns=[tuple(c) for c in item.get("columns", [])],
            )
            for item in items
        ]
    return out
