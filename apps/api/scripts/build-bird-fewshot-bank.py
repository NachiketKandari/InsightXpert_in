"""Build a curated BIRD few-shot bank from dev.json.

Usage:
    uv run python scripts/build-bird-fewshot-bank.py \
        --dev /path/to/bird/dev.json

Writes to apps/api/src/insightxpert_api/sample_questions/fixtures/bird_examples.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KEEP_DBS: list[str] = [
    "california_schools",
    "card_games",
    "financial",
    "formula_1",
    "student_club",
    "superhero",
    "european_football_2",
    "thrombosis_prediction",
    "toxicology",
    "codebase_community",
]

# Maximum questions to emit per db_id (before category curation)
MAX_PER_DB = 8

# Output path relative to this script's location (scripts/ -> apps/api/)
_SCRIPT_DIR = Path(__file__).parent
OUTPUT = (
    _SCRIPT_DIR.parent
    / "src/insightxpert_api/sample_questions/fixtures/bird_examples.json"
)


def _is_short_single_sentence_question(q: str) -> bool:
    """True if the question ends with ? and is ≤25 words."""
    return q.endswith("?") and len(q.split()) <= 25


def _build_features(db_id: str, question: str) -> dict[str, bool]:
    """Heuristically assign the 5 boolean feature flags."""
    q_lower = question.lower()

    temporal_keywords = (
        "year", "month", "date", "time", "season", "period",
        "annual", "over the", "trend", "history",
        "2010", "2011", "2012", "2013", "2014", "2015",
        "2016", "2017", "2018", "2019", "2020",
    )
    geo_dbs = {"california_schools", "financial"}
    geo_keywords = ("country", "region", "city", "county", "location", "circuit")

    has_temporal = any(kw in q_lower for kw in temporal_keywords)
    has_categorical = any(
        kw in q_lower
        for kw in ("type", "kind", "category", "which", "what", "group", "class", "gender", "sex")
    )
    has_numeric_metric = any(
        kw in q_lower
        for kw in (
            "how many", "average", "total", "highest", "lowest", "most", "least",
            "count", "number", "percentage", "ratio", "rate", "score",
        )
    )
    has_geo = db_id in geo_dbs or any(kw in q_lower for kw in geo_keywords)
    has_relations = True  # all BIRD dbs are relational

    return {
        "has_temporal": has_temporal,
        "has_categorical": has_categorical,
        "has_numeric_metric": has_numeric_metric,
        "has_geo": has_geo,
        "has_relations": has_relations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BIRD few-shot bank")
    parser.add_argument("--dev", required=True, help="Path to BIRD dev.json")
    args = parser.parse_args()

    dev_path = Path(args.dev)
    if not dev_path.exists():
        print(f"ERROR: dev.json not found at {dev_path}", file=sys.stderr)
        sys.exit(1)

    raw: list[dict] = json.loads(dev_path.read_text())

    entries: list[dict] = []
    for db_id in KEEP_DBS:
        db_qs = [
            r["question"]
            for r in raw
            if r["db_id"] == db_id and _is_short_single_sentence_question(r["question"])
        ]
        # Take up to MAX_PER_DB; spread = pick every Nth to get variety
        step = max(1, len(db_qs) // MAX_PER_DB)
        selected = db_qs[::step][:MAX_PER_DB]
        for q in selected:
            entries.append(
                {
                    "db_id": db_id,
                    "category": "Comparative",  # placeholder — hand-curated below
                    "features": _build_features(db_id, q),
                    "question": q,
                }
            )

    OUTPUT.write_text(json.dumps(entries, indent=2) + "\n")
    print(f"Wrote {len(entries)} entries → {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
