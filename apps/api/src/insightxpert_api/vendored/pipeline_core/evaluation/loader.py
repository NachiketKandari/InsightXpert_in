import json
import logging
from pathlib import Path

from insightxpert_api.vendored.pipeline_core.models.evaluation import TestCase

logger = logging.getLogger(__name__)


def _available_db_ids(db_dir: Path, benchmark: str) -> set[str] | None:
    """Return set of db_ids that have local database files, or None to skip filtering."""
    if benchmark == "spider_snow":
        return None  # all DBs are on Snowflake, no local files to check
    if benchmark == "mini_dev":
        return {
            p.name
            for p in db_dir.iterdir()
            if p.is_dir() and (p / f"{p.name}.sqlite").exists()
        }
    return {p.stem for p in db_dir.glob("*.sqlite")}


def load_test_cases(
    test_file: Path,
    db_id: str | None = None,
    difficulty: str | None = None,
    limit: int | None = None,
    db_dir: Path | None = None,
    question_ids: list[int] | None = None,
    benchmark: str = "bird_dev",
) -> list[TestCase]:
    """Load test cases from a BIRD-format JSON file, optionally filtered.

    If db_dir is provided, only include test cases whose database exists there.
    If question_ids is provided, only those IDs are returned (overrides limit).
    benchmark controls how available databases are detected (flat vs nested).
    """
    logger.debug(
        "Loading test cases from %s (db_id=%s, difficulty=%s, limit=%s, question_ids=%s)",
        test_file, db_id, difficulty, limit, question_ids,
    )
    with open(test_file) as f:
        raw = json.load(f)

    available_dbs: set[str] | None = None
    if db_dir is not None:
        available_dbs = _available_db_ids(Path(db_dir), benchmark)
        logger.debug("Available databases: %s", sorted(available_dbs) if available_dbs is not None else "all (Snowflake)")

    id_filter: set[int] | None = set(question_ids) if question_ids else None

    cases: list[TestCase] = []
    for item in raw:
        if available_dbs is not None and item["db_id"] not in available_dbs:
            continue
        if db_id is not None and item["db_id"] != db_id:
            continue
        if difficulty is not None and item.get("difficulty") != difficulty:
            continue
        if id_filter is not None and item["question_id"] not in id_filter:
            continue

        cases.append(
            TestCase(
                question_id=item["question_id"],
                db_id=item["db_id"],
                question=item["question"],
                evidence=item.get("evidence", ""),
                gold_sql=item["SQL"],
                difficulty=item.get("difficulty", "simple"),
            )
        )

        if id_filter is None and limit is not None and len(cases) >= limit:
            break

    return cases
