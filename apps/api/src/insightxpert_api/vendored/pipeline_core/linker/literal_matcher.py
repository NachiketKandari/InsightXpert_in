"""Match extracted string literals to database columns via LSH."""
import logging
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHIndex

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)

# Column types whose values are useful as literal revision hints.
# Numeric / ID columns produce noisy matches (e.g. Player.id for literal "2010").
_TEXT_TYPES = {"TEXT", "VARCHAR", "CHAR", "NVARCHAR", "NCHAR", "CLOB", "STRING"}


class LiteralMatcher:
    """Uses LSH index to find columns whose values resemble extracted literals."""

    def __init__(self, lsh_index: LSHIndex) -> None:
        self._lsh = lsh_index

    def match(self, literals: set[str]) -> set[tuple[str, str]]:
        """For each literal, query LSH and return (table, column) pairs.

        Skips literals shorter than 2 characters (too noisy for LSH matching).
        """
        matched, _, _ = self.match_detailed(literals)
        return matched

    def match_detailed(
        self, literals: set[str],
    ) -> tuple[set[tuple[str, str]], set[str], dict[str, list[str]]]:
        """Match literals via LSH with full detail.

        Returns:
            matched_cols: all (table, column) pairs across all literals
            unmatched: literals with zero LSH hits
            literal_to_cols: maps each literal to its matching "table.column" IDs
        """
        matched: set[tuple[str, str]] = set()
        unmatched: set[str] = set()
        literal_to_cols: dict[str, list[str]] = {}

        for literal in literals:
            if not literal or len(literal) < 2:
                continue
            col_ids = self._lsh.query(literal)
            literal_to_cols[literal] = col_ids
            if not col_ids:
                unmatched.add(literal)
            for col_id in col_ids:
                parts = col_id.split(".", 1)
                if len(parts) == 2:
                    matched.add((parts[0], parts[1]))
            if col_ids:
                logger.debug("Literal %r matched: %s", literal, col_ids)

        logger.info(
            "LiteralMatcher: %d literals -> %d column matches, %d unmatched",
            len(literals), len(matched), len(unmatched),
        )
        return matched, unmatched, literal_to_cols

    def match_with_values(
        self,
        literals: set[str],
        schema: "DatabaseSchema | None" = None,
    ) -> dict[str, dict[str, list[str]]]:
        """Match literals and return actual DB values for each.

        Args:
            schema: when provided, only return value hints for text-like columns
                (TEXT, VARCHAR, etc.). This filters out noisy matches from
                numeric/ID columns (e.g., Player.id matching literal "2010").

        Returns:
            dict mapping each literal -> { "table.column": [matching_values] }
        """
        # Build a set of text-type columns for fast lookup
        text_cols: set[str] | None = None
        if schema is not None:
            text_cols = set()
            for table in schema.tables:
                for col in table.columns:
                    if col.type.upper().split("(")[0].strip() in _TEXT_TYPES:
                        text_cols.add(f"{table.name}.{col.name}")

        result: dict[str, dict[str, list[str]]] = {}
        for literal in literals:
            if not literal or len(literal) < 2:
                continue
            col_values = self._lsh.query_with_values(literal)
            if col_values:
                # Filter to text columns if schema available
                if text_cols is not None:
                    col_values = {
                        col_id: vals
                        for col_id, vals in col_values.items()
                        if col_id in text_cols
                    }
                if col_values:
                    result[literal] = col_values
        return result
