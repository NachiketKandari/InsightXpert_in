"""Pure trigger evaluator. Stateless — no DB access.

Ported from the public fork's ``evaluator.py`` with the ``slope`` case
entirely removed. Supported trigger types:
    * ``threshold`` — compare a scalar from the first row against a value.
    * ``row_count`` — compare ``len(rows)`` against a value.
    * ``change_detection`` — percent change vs a previous run's scalar.
    * ``column_expression`` — any_row / all_rows predicate over a column.

Inputs are plain dicts (``result`` is ``{"columns": [...], "rows": [...]}`` where
rows are ``list[list[Any]]`` OR ``list[dict]``; both are tolerated).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("insightxpert_api.automations.evaluator")

OPERATORS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}

OP_SYMBOL = {
    "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "ne": "!=",
}


def _row_as_dict(row: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    # assume sequence aligned with columns
    return {c: row[i] if i < len(row) else None for i, c in enumerate(columns)}


def _extract_scalar(
    result: dict, column: str | None = None
) -> float | None:
    rows = result.get("rows", [])
    columns = list(result.get("columns", []))
    if not rows:
        return None
    first_row = _row_as_dict(rows[0], columns)

    if column is not None:
        val = first_row.get(column)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    # Heuristic: 1 numeric column
    numeric_cols: list[str] = []
    for col in columns:
        val = first_row.get(col)
        if val is None:
            continue
        try:
            float(val)
            numeric_cols.append(col)
        except (TypeError, ValueError):
            pass
    if numeric_cols:
        try:
            return float(first_row[numeric_cols[0]])
        except (TypeError, ValueError):
            return None
    return None


class TriggerEvaluator:
    """Evaluate a list of trigger conditions against one run result."""

    def evaluate(
        self,
        conditions: list[dict],
        result: dict,
        previous_result: dict | None = None,
    ) -> list[dict]:
        return [self._evaluate_one(c, result, previous_result) for c in conditions]

    def any_fired(self, trigger_results: list[dict]) -> bool:
        return any(r.get("fired") for r in trigger_results)

    def _evaluate_one(
        self,
        condition: dict,
        result: dict,
        previous_result: dict | None,
    ) -> dict:
        cond_type = condition.get("type", "")
        try:
            if cond_type == "threshold":
                return self._eval_threshold(condition, result)
            if cond_type == "row_count":
                return self._eval_row_count(condition, result)
            if cond_type == "change_detection":
                return self._eval_change_detection(condition, result, previous_result)
            if cond_type == "column_expression":
                return self._eval_column_expression(condition, result)
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": f"Unknown trigger type: {cond_type}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("trigger evaluation error: %s", exc)
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": f"Error: {exc}",
            }

    def _eval_threshold(self, condition: dict, result: dict) -> dict:
        column = condition.get("column")
        operator = condition.get("operator", "gt")
        threshold = condition.get("value")

        if threshold is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": "No threshold value specified",
            }

        actual = _extract_scalar(result, column)
        if actual is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": "Could not extract scalar value",
            }

        op_fn = OPERATORS.get(operator)
        if op_fn is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": actual,
                "message": f"Unknown operator: {operator}",
            }

        fired = op_fn(actual, threshold)
        sym = OP_SYMBOL.get(operator, operator)
        msg = (
            f"Value {actual} {sym} {threshold}" if fired
            else f"Value {actual} did not meet threshold {sym} {threshold}"
        )
        return {
            "condition": condition,
            "fired": fired,
            "actual_value": actual,
            "message": msg,
        }

    def _eval_row_count(self, condition: dict, result: dict) -> dict:
        operator = condition.get("operator", "gt")
        threshold = condition.get("value", 0)
        rows = result.get("rows", [])
        actual = len(rows)

        op_fn = OPERATORS.get(operator)
        if op_fn is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": actual,
                "message": f"Unknown operator: {operator}",
            }

        fired = op_fn(actual, threshold)
        sym = OP_SYMBOL.get(operator, operator)
        msg = (
            f"Row count {actual} triggered (threshold: {sym} {threshold})"
            if fired
            else f"Row count {actual} did not trigger (threshold: {sym} {threshold})"
        )
        return {
            "condition": condition,
            "fired": fired,
            "actual_value": actual,
            "message": msg,
        }

    def _eval_change_detection(
        self,
        condition: dict,
        result: dict,
        previous_result: dict | None,
    ) -> dict:
        if previous_result is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": "No previous run for comparison",
            }

        column = condition.get("column")
        change_pct = condition.get("change_percent", 10.0)

        current = _extract_scalar(result, column)
        previous = _extract_scalar(previous_result, column)

        if current is None or previous is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": current,
                "message": "Could not extract values for comparison",
            }

        if previous == 0:
            pct_change = 100.0 if current != 0 else 0.0
        else:
            pct_change = abs((current - previous) / previous) * 100

        fired = pct_change >= change_pct
        msg = (
            f"Changed {pct_change:.1f}% (from {previous} to {current})" if fired
            else f"Changed only {pct_change:.1f}% (threshold: {change_pct}%)"
        )
        return {
            "condition": condition,
            "fired": fired,
            "actual_value": pct_change,
            "message": msg,
        }

    def _eval_column_expression(self, condition: dict, result: dict) -> dict:
        column = condition.get("column")
        operator = condition.get("operator", "gt")
        threshold = condition.get("value")
        scope = condition.get("scope", "any_row")

        if not column or threshold is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": "Column and value required",
            }

        rows = result.get("rows", [])
        columns = list(result.get("columns", []))
        if not rows:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": "No rows to evaluate",
            }

        op_fn = OPERATORS.get(operator)
        if op_fn is None:
            return {
                "condition": condition,
                "fired": False,
                "actual_value": None,
                "message": f"Unknown operator: {operator}",
            }

        matches = 0
        for row in rows:
            rd = _row_as_dict(row, columns)
            val = rd.get(column)
            if val is None:
                continue
            try:
                if op_fn(float(val), threshold):
                    matches += 1
            except (TypeError, ValueError):
                pass

        if scope == "all_rows":
            fired = matches == len(rows) and len(rows) > 0
        else:
            fired = matches > 0

        msg = (
            f"{matches}/{len(rows)} rows matched ({scope})" if fired
            else f"Only {matches}/{len(rows)} rows matched ({scope})"
        )
        return {
            "condition": condition,
            "fired": fired,
            "actual_value": matches,
            "message": msg,
        }


__all__ = ["TriggerEvaluator", "OPERATORS"]
