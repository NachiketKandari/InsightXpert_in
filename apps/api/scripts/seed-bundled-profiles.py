#!/usr/bin/env python3
"""Seed quirk-enriched ``DatabaseProfile`` rows for bundled BIRD sample DBs.

Companion to ``fetch-bundled-dbs.sh``: that script copies the SQLite files,
this one populates ``database_profiles`` so the bundled DBs ship with their
fully-enriched profiles (column summaries + quirks: aliases, enum_labels,
fk_alias, semantic_hint, etc.) instead of forcing a per-tenant re-profile.

Source: ``Private/InsightXpert-Research/profiles/mini_dev/<db_id>/profile.json``
(override with ``BUNDLED_PROFILES_SOURCE`` for CI/Docker).

Skips bundled DBs with no available profile (currently: ``transactions``) and
logs a clear notice rather than failing the whole batch.

Usage::

    cd apps/api
    .venv/bin/python scripts/seed-bundled-profiles.py
    # or, to re-seed from a different checkout:
    BUNDLED_PROFILES_SOURCE=/path/to/research/profiles/mini_dev \\
        .venv/bin/python scripts/seed-bundled-profiles.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make `src/` importable when the script is run directly.
_API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_API_ROOT / "src"))

from insightxpert_api.config import get_settings  # noqa: E402
from insightxpert_api.llm.gemini import GeminiLLM  # noqa: E402
from insightxpert_api.profiling import repository as profiles_repo  # noqa: E402
from insightxpert_api.sample_questions import repository as sq_repo  # noqa: E402
from insightxpert_api.sample_questions.generator import (  # noqa: E402
    generate_sample_questions,
)
from insightxpert_api.vendored.pipeline_core.models.profile import (  # noqa: E402
    DatabaseProfile,
)


def _adapt_llm(llm):
    """Adapt GeminiLLM (single-prompt) to the two-arg (system, user) interface."""
    if llm is None:
        return None

    class _Adapter:
        async def async_generate(self, system: str, user: str) -> str:
            return await llm.async_generate(f"{system}\n\n{user}")

    return _Adapter()

# Bundled DB ids — keep in sync with apps/api/Databases/_shared/*.sqlite.
_BUNDLED_DB_IDS = (
    "california_schools",
    "debit_card_specializing",
    "european_football_2",
    "financial",
    "formula_1",
    "toxicology",
    "transactions",
)

_DEFAULT_SOURCE = (
    "/Users/nachiket/workspace/github.com/Private/"
    "InsightXpert-Research/profiles/mini_dev"
)
_GENERATED_BY = "seed-bundled-profiles"


def _profile_path(source_root: Path, db_id: str) -> Path:
    return source_root / db_id / "profile.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed bundled DB profiles (and sample questions).")
    parser.add_argument(
        "--db-id",
        metavar="DB_ID",
        help="Seed only this DB id instead of all bundled DBs.",
    )
    args = parser.parse_args()

    source_root = Path(os.environ.get("BUNDLED_PROFILES_SOURCE", _DEFAULT_SOURCE))
    if not source_root.is_dir():
        print(f"ERROR: source dir not found: {source_root}", file=sys.stderr)
        print("Set BUNDLED_PROFILES_SOURCE to override.", file=sys.stderr)
        return 1

    settings = get_settings()
    raw_llm = (
        GeminiLLM(api_key=settings.gemini_api_key, model=settings.gemini_chat_model)
        if settings.gemini_api_key
        else None
    )
    adapted_llm = _adapt_llm(raw_llm)

    db_ids = (args.db_id,) if args.db_id else _BUNDLED_DB_IDS

    seeded: list[str] = []
    skipped: list[tuple[str, str]] = []

    for db_id in db_ids:
        path = _profile_path(source_root, db_id)
        if not path.exists():
            skipped.append((db_id, f"no profile.json at {path}"))
            continue

        try:
            text = path.read_text()
            profile = DatabaseProfile.model_validate_json(text)
        except Exception as exc:  # pragma: no cover — operator-facing
            skipped.append((db_id, f"validation failed: {type(exc).__name__}: {exc}"))
            continue

        # Re-serialize through the model so we store a canonical shape, not
        # whatever extra/missing fields the on-disk JSON happened to have.
        profiles_repo.upsert(
            db_id=db_id,
            profile_kind="base",
            owner_user_id=None,  # bundled = system-owned
            generated_by=_GENERATED_BY,
            profile_json=profile.model_dump_json(),
        )
        n_cols = sum(len(t.columns) for t in profile.tables)
        n_quirks = sum(
            1 for t in profile.tables for c in t.columns if c.quirks is not None
        )

        sq = asyncio.run(
            generate_sample_questions(
                profile,
                llm=adapted_llm,
                model_name=settings.gemini_chat_model,
            )
        )
        sq_repo.set_sample_questions(db_id, sq)
        print(f"  sample_questions: {sq.status.value}")

        seeded.append(f"{db_id} (tables={len(profile.tables)} cols={n_cols} quirks={n_quirks})")

    print(f"Seeded {len(seeded)} profile(s):")
    for line in seeded:
        print(f"  ✓ {line}")
    if skipped:
        print(f"\nSkipped {len(skipped)}:")
        for db_id, reason in skipped:
            print(f"  - {db_id}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
