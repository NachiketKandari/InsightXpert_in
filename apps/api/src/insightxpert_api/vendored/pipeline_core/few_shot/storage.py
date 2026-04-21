"""Disk layout for the few-shot retrieval index.

Two files per benchmark, sitting under ``few_shot/`` at the project root:

- ``few_shot_<benchmark>.json`` — the sampled QA pairs (human-readable).
- ``few_shot_<benchmark>.npz`` — per-DB embedding matrices, stored as one numpy
  array per db_id with key ``"emb__<db_id>"``. Row order matches the JSON.
"""
from __future__ import annotations

from pathlib import Path

FEW_SHOT_DIR = Path("few_shot")
EMB_KEY_PREFIX = "emb__"


def qa_pairs_path(benchmark: str) -> Path:
    return FEW_SHOT_DIR / f"few_shot_{benchmark}.json"


def embeddings_path(benchmark: str) -> Path:
    return FEW_SHOT_DIR / f"few_shot_{benchmark}.npz"


def emb_key(db_id: str) -> str:
    return f"{EMB_KEY_PREFIX}{db_id}"


def db_id_from_key(key: str) -> str:
    return key[len(EMB_KEY_PREFIX):] if key.startswith(EMB_KEY_PREFIX) else key
