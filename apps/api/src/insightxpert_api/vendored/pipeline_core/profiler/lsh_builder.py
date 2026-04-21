import logging
import pickle
from pathlib import Path

from datasketch import MinHash, MinHashLSH

from insightxpert_api.vendored.pipeline_core.db import Database
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)

# Paper: N=10,000 distinct values, character 3-gram shingling, threshold=0.5
_MAX_VALUES = 10_000
_NUM_PERM = 128
_THRESHOLD = 0.5
_NGRAM_SIZE = 3


def _shingles(text: str, n: int = _NGRAM_SIZE) -> set[str]:
    """Return the set of character n-grams for text (lowercased)."""
    s = text.lower()
    if len(s) < n:
        return {s}
    return {s[i: i + n] for i in range(len(s) - n + 1)}


def _minhash(text: str) -> MinHash:
    """Build a MinHash signature for text using character n-gram shingling."""
    m = MinHash(num_perm=_NUM_PERM)
    for shingle in _shingles(text):
        m.update(shingle.encode("utf-8"))
    return m


class LSHIndex:
    """Queryable LSH index over column values for one database."""

    def __init__(self, lsh: MinHashLSH, value_to_columns: dict[str, list[str]]):
        self._lsh = lsh
        # Maps each indexed value key → list of "table.column" identifiers
        self._value_to_columns = value_to_columns

    def query(self, text: str) -> list[str]:
        """Return list of 'table.column' identifiers whose values resemble text."""
        m = _minhash(text)
        keys = self._lsh.query(m)
        columns: list[str] = []
        seen: set[str] = set()
        for key in keys:
            for col_id in self._value_to_columns.get(key, []):
                if col_id not in seen:
                    columns.append(col_id)
                    seen.add(col_id)
        return columns

    def query_with_values(self, text: str) -> dict[str, list[str]]:
        """Return mapping of 'table.column' -> list of actual matching values.

        Unlike query() which only returns column IDs, this also extracts
        the concrete DB values from the LSH keys (format: 'col_id::value').
        """
        m = _minhash(text)
        keys = self._lsh.query(m)
        col_values: dict[str, list[str]] = {}
        for key in keys:
            # key format: "Table.column::actual_value"
            if "::" not in key:
                continue
            col_id, value = key.split("::", 1)
            col_values.setdefault(col_id, []).append(value)
        return col_values

    def save(self, path: Path) -> None:
        """Pickle the entire index to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "LSHIndex":
        """Load a previously pickled LSHIndex from disk."""
        with open(path, "rb") as f:
            return pickle.load(f)


class LSHBuilder:
    """Builds an LSHIndex by shingling column values from a database."""

    def build(self, db: Database, schema: DatabaseSchema) -> LSHIndex:
        """Index up to N distinct values per column across all tables."""
        total_cols = sum(len(t.columns) for t in schema.tables)
        logger.debug("Building LSH index for '%s' (%d columns)", schema.db_id, total_cols)
        lsh = MinHashLSH(threshold=_THRESHOLD, num_perm=_NUM_PERM)
        value_to_columns: dict[str, list[str]] = {}

        for table in schema.tables:
            for col in table.columns:
                col_id = f"{table.name}.{col.name}"
                self._index_column(db, table.name, col.name, col_id, lsh, value_to_columns)

        logger.debug("LSH index built: %d unique keys", len(value_to_columns))
        return LSHIndex(lsh=lsh, value_to_columns=value_to_columns)

    def _index_column(
        self,
        db: Database,
        table: str,
        column: str,
        col_id: str,
        lsh: MinHashLSH,
        value_to_columns: dict[str, list[str]],
    ) -> None:
        """Fetch distinct values for one column and insert their MinHash signatures into the LSH."""
        rows = db.execute(
            f'SELECT DISTINCT CAST("{column}" AS TEXT) FROM "{table}"'
            f' WHERE "{column}" IS NOT NULL LIMIT {_MAX_VALUES}'
        )
        for (value,) in rows:
            if not value:
                continue
            key = f"{col_id}::{value}"
            m = _minhash(value)
            try:
                lsh.insert(key, m)
            except ValueError:
                # Key already inserted — shouldn't happen with unique (col_id::value) keys
                logger.warning("Duplicate LSH key skipped: '%s'", key)
            value_to_columns.setdefault(key, []).append(col_id)
