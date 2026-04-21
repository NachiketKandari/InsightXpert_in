"""SQL literal discovery: search actual DB for question nouns/entities in TEXT columns."""
from __future__ import annotations

import logging
import re

from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)

# Common English words to skip when extracting candidate literals
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "my", "your", "his", "its", "our", "their", "this", "that", "these",
    "those", "who", "whom", "which", "what", "where", "when", "how", "why",
    "all", "each", "every", "both", "few", "more", "most", "other", "some",
    "such", "no", "not", "only", "same", "so", "than", "too", "very",
    "of", "in", "to", "for", "with", "on", "at", "from", "by", "about",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "nor", "if", "while", "because", "until",
    "although", "since", "unless", "also", "just", "still", "already",
    "many", "much", "any", "find", "list", "show", "give", "get", "tell",
    "name", "number", "total", "count", "average", "sum", "maximum",
    "minimum", "highest", "lowest", "least", "percentage", "ratio", "rate",
    "among", "per", "across", "there", "here", "up", "down",
})

# Regex patterns for extracting candidate literals
_QUOTED_RE = re.compile(r"""['"]([^'"]{2,})['"]""")
_CAPITALIZED_RE = re.compile(r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)\b")


def _extract_candidates(question: str) -> set[str]:
    """Extract candidate literals from the question text.

    Extracts:
    - Quoted strings (single or double quotes)
    - Capitalized words/phrases (proper nouns), excluding sentence-start words
    - Numbers
    """
    candidates: set[str] = set()

    # Quoted strings
    for match in _QUOTED_RE.finditer(question):
        candidates.add(match.group(1).strip())

    # Capitalized words/phrases (skip sentence-start position)
    sentences = re.split(r"[.!?]\s+", question)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        # Skip the first word (sentence start) — find capitalized words after it
        first_space = sentence.find(" ")
        if first_space == -1:
            continue
        rest = sentence[first_space:]
        for match in _CAPITALIZED_RE.finditer(rest):
            word = match.group(1)
            if word.lower() not in _STOP_WORDS and len(word) >= 2:
                candidates.add(word)

    return candidates


def _is_text_type(col_type: str) -> bool:
    """Check if a column type is text-like (for LIKE matching)."""
    t = col_type.upper()
    return any(kw in t for kw in ("TEXT", "CHAR", "VARCHAR", "CLOB", "STRING"))


def discover_literal_columns(
    question: str,
    schema: DatabaseSchema,
    db_id: str,
    benchmark: str,
) -> set[tuple[str, str]]:
    """Search actual DB for question nouns/entities in TEXT columns.

    Returns a set of (table_name, column_name) pairs where a candidate
    literal from the question was found via LIKE matching.
    """
    candidates = _extract_candidates(question)
    if not candidates:
        logger.debug("Literal discovery: no candidate literals extracted from question")
        return set()

    logger.debug("Literal discovery: %d candidates — %s", len(candidates), candidates)

    # Collect TEXT columns from schema
    text_columns: list[tuple[str, str]] = []
    for table in schema.tables:
        for col in table.columns:
            if _is_text_type(col.type):
                text_columns.append((table.name, col.name))

    if not text_columns:
        logger.debug("Literal discovery: no TEXT columns in schema")
        return set()

    matched: set[tuple[str, str]] = set()
    try:
        with open_db(db_id, benchmark=benchmark) as db:
            for candidate in candidates:
                # Try exact match first (faster, uses indexes)
                exact_hit = False
                for table_name, col_name in text_columns:
                    try:
                        rows = db.execute(
                            f'SELECT 1 FROM "{table_name}" WHERE "{col_name}" = ? LIMIT 1',
                            (candidate,),
                        )
                        if rows:
                            matched.add((table_name, col_name))
                            exact_hit = True
                    except Exception:
                        continue
                # Fall back to LIKE only if no exact match found
                if not exact_hit:
                    for table_name, col_name in text_columns:
                        try:
                            rows = db.execute(
                                f'SELECT 1 FROM "{table_name}" WHERE "{col_name}" LIKE ? LIMIT 1',
                                (f"%{candidate}%",),
                            )
                            if rows:
                                matched.add((table_name, col_name))
                        except Exception:
                            continue
    except FileNotFoundError:
        logger.warning("Literal discovery: database %s not found for benchmark %s", db_id, benchmark)
        return set()

    logger.debug("Literal discovery: %d columns matched", len(matched))
    return matched
