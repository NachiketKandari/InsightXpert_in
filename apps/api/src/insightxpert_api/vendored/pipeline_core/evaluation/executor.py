"""Execute SQL queries against a Database and compute result-set equality."""
import logging
from dataclasses import dataclass

from insightxpert_api.vendored.pipeline_core.db import Database, open_db
from insightxpert_api.vendored.pipeline_core.models.query import QueryResult

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of verifying a candidate SQL against a gold SQL."""
    question_id: int
    db_id: str
    predicted_sql: str
    gold_sql: str
    is_correct: bool
    predicted_rows: int | None = None  # None if execution failed
    gold_rows: int | None = None       # None if execution failed
    error: str | None = None


def verify_candidate(
    db_id: str,
    predicted_sql: str,
    gold_sql: str,
    question_id: int = 0,
) -> VerificationResult:
    """Standalone utility: check whether predicted_sql produces the same result as gold_sql.

    Opens and closes its own DB connection — safe to call ad-hoc outside the eval loop.
    Logs a one-line verdict at INFO level so it's visible without digging into debug logs.

    Usage::

        from insightxpert_api.vendored.pipeline_core.evaluation.executor import verify_candidate
        result = verify_candidate(
            db_id="toxicology",
            predicted_sql="SELECT ...",
            gold_sql="SELECT ...",
            question_id=198,
        )
        print(result.is_correct, result.error)
    """
    executor = SQLExecutor()
    try:
        with open_db(db_id) as db:
            pred_result = executor.execute(db, predicted_sql)
            gold_result = executor.execute(db, gold_sql)
    except Exception as e:
        logger.error("verify_candidate: DB open failed for '%s': %s", db_id, e)
        return VerificationResult(
            question_id=question_id, db_id=db_id,
            predicted_sql=predicted_sql, gold_sql=gold_sql,
            is_correct=False, error=str(e),
        )

    if pred_result.error:
        logger.info(
            "verify_candidate [%s] question=%d → WRONG (predicted SQL error: %s)",
            db_id, question_id, pred_result.error,
        )
        return VerificationResult(
            question_id=question_id, db_id=db_id,
            predicted_sql=predicted_sql, gold_sql=gold_sql,
            is_correct=False, error=pred_result.error,
        )

    if gold_result.error:
        logger.warning(
            "verify_candidate [%s] question=%d → gold SQL error: %s",
            db_id, question_id, gold_result.error,
        )
        return VerificationResult(
            question_id=question_id, db_id=db_id,
            predicted_sql=predicted_sql, gold_sql=gold_sql,
            is_correct=False, error=f"gold SQL error: {gold_result.error}",
        )

    # BIRD benchmark EX metric: unordered set equality (matches evaluation_ex.py)
    is_correct = set(tuple(r) for r in pred_result.rows) == set(tuple(r) for r in gold_result.rows)

    logger.info(
        "verify_candidate [%s] question=%d → %s  (predicted=%d rows, gold=%d rows)",
        db_id, question_id,
        "CORRECT ✓" if is_correct else "WRONG ✗",
        len(pred_result.rows), len(gold_result.rows),
    )
    return VerificationResult(
        question_id=question_id, db_id=db_id,
        predicted_sql=predicted_sql, gold_sql=gold_sql,
        is_correct=is_correct,
        predicted_rows=len(pred_result.rows),
        gold_rows=len(gold_result.rows),
    )


class SQLExecutor:
    def execute(self, db: Database, sql: str) -> QueryResult:
        """Run sql against db and return a QueryResult.

        On success, rows contains the result tuples and columns is derived from
        the cursor description. On any exception, error is populated instead.
        """
        try:
            rows = db.execute(sql)
            # Derive column names from the first row's keys if available.
            # Since db.execute returns plain tuples we infer columns via a
            # separate cursor-description query using the same connection.
            columns = self._column_names(db, sql)
            logger.debug("Executed SQL: %d rows returned", len(rows))
            return QueryResult(sql=sql, rows=[list(r) for r in rows], columns=columns)
        except Exception as e:
            logger.warning("SQL execution error: %s", e)
            return QueryResult(sql=sql, error=str(e))

    def _column_names(self, db: Database, sql: str) -> list[str]:
        """Return column names for the given SELECT.

        Uses db.column_names() if available (SnowflakeDatabase has this), otherwise
        falls back to SQLite cursor.description via the internal connection.
        """
        try:
            # Prefer public column_names method (SnowflakeDatabase has this)
            if hasattr(db, "column_names"):
                return db.column_names(sql)

            # Fallback: SQLite — access internal connection for cursor.description
            meta_sql = f"SELECT * FROM ({sql}) AS _meta LIMIT 0"
            conn = getattr(db, "_conn", None)
            if conn is not None:
                cur = conn.cursor()
                cur.execute(meta_sql)
                if cur.description:
                    return [d[0] for d in cur.description]
        except Exception as exc:
            logger.debug("Could not retrieve column names: %s", exc)
        return []

    def execution_match(self, db: Database, predicted_sql: str, gold_sql: str) -> bool:
        """BIRD benchmark metric: result-set equality regardless of row/column order."""
        pred_result = self.execute(db, predicted_sql)
        gold_result = self.execute(db, gold_sql)

        if pred_result.error or gold_result.error:
            return False

        # BIRD benchmark EX metric: unordered set equality (matches evaluation_ex.py)
        return (
            set(tuple(r) for r in pred_result.rows)
            == set(tuple(r) for r in gold_result.rows)
        )

    def execution_match_relaxed(self, db: Database, predicted_sql: str, gold_sql: str) -> bool:
        """Relaxed EX metric: tolerates extra columns in predicted results.

        Returns True if the gold result columns appear as a contiguous
        subsequence within the predicted result columns (same row data,
        predicted may have additional columns).
        """
        pred_result = self.execute(db, predicted_sql)
        gold_result = self.execute(db, gold_sql)

        if pred_result.error or gold_result.error:
            return False

        pred_rows = pred_result.rows
        gold_rows = gold_result.rows

        if not gold_rows:
            return not pred_rows

        gold_ncols = len(gold_rows[0])
        pred_ncols = len(pred_rows[0]) if pred_rows else 0

        if pred_ncols < gold_ncols:
            return False

        if pred_ncols == gold_ncols:
            return (
                set(tuple(r) for r in pred_rows)
                == set(tuple(r) for r in gold_rows)
            )

        gold_set = set(tuple(r) for r in gold_rows)
        # Slide a window of gold_ncols across predicted columns
        for start in range(pred_ncols - gold_ncols + 1):
            projected = set(tuple(r[start:start + gold_ncols]) for r in pred_rows)
            if projected == gold_set:
                return True
        return False
