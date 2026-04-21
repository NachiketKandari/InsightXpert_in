"""Unit tests for the pure trigger evaluator."""

from __future__ import annotations

from insightxpert_api.automations.evaluator import TriggerEvaluator


def _result(columns, rows):
    return {"columns": columns, "rows": rows}


def test_threshold_fires_when_greater():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "threshold", "operator": "gt", "value": 10, "column": "n"}],
        _result(["n"], [{"n": 42}]),
    )
    assert out[0]["fired"] is True
    assert out[0]["actual_value"] == 42.0


def test_threshold_does_not_fire_when_less_than():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "threshold", "operator": "gt", "value": 100, "column": "n"}],
        _result(["n"], [{"n": 5}]),
    )
    assert out[0]["fired"] is False


def test_threshold_missing_column():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "threshold", "operator": "gt", "value": 1, "column": "missing"}],
        _result(["n"], [{"n": 5}]),
    )
    assert out[0]["fired"] is False
    assert "Could not extract" in out[0]["message"]


def test_threshold_empty_result():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "threshold", "operator": "gt", "value": 1, "column": "n"}],
        _result(["n"], []),
    )
    assert out[0]["fired"] is False


def test_row_count_fires_gt():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "row_count", "operator": "gt", "value": 2}],
        _result(["n"], [{"n": 1}, {"n": 2}, {"n": 3}]),
    )
    assert out[0]["fired"] is True
    assert out[0]["actual_value"] == 3


def test_row_count_does_not_fire():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "row_count", "operator": "gt", "value": 10}],
        _result(["n"], [{"n": 1}]),
    )
    assert out[0]["fired"] is False


def test_row_count_empty_result():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "row_count", "operator": "eq", "value": 0}],
        _result(["n"], []),
    )
    assert out[0]["fired"] is True  # empty == 0
    assert out[0]["actual_value"] == 0


def test_row_count_missing_column_is_ignored():
    """row_count ignores column; verifies regressions don't sneak in a column ref."""
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "row_count", "operator": "gte", "value": 1, "column": "unused"}],
        _result(["n"], [{"n": 1}]),
    )
    assert out[0]["fired"] is True


def test_change_detection_fires_when_percent_exceeded():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [
            {
                "type": "change_detection",
                "column": "n",
                "change_percent": 10.0,
            }
        ],
        _result(["n"], [{"n": 200}]),
        previous_result=_result(["n"], [{"n": 100}]),
    )
    assert out[0]["fired"] is True


def test_change_detection_does_not_fire():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "change_detection", "column": "n", "change_percent": 50.0}],
        _result(["n"], [{"n": 101}]),
        previous_result=_result(["n"], [{"n": 100}]),
    )
    assert out[0]["fired"] is False


def test_change_detection_no_previous_run():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "change_detection", "column": "n", "change_percent": 10.0}],
        _result(["n"], [{"n": 100}]),
        previous_result=None,
    )
    assert out[0]["fired"] is False
    assert "previous run" in out[0]["message"].lower()


def test_change_detection_empty_previous():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "change_detection", "column": "n", "change_percent": 10.0}],
        _result(["n"], [{"n": 100}]),
        previous_result=_result(["n"], []),
    )
    assert out[0]["fired"] is False


def test_column_expression_any_row_fires():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [
            {
                "type": "column_expression",
                "column": "score",
                "operator": "gt",
                "value": 90,
                "scope": "any_row",
            }
        ],
        _result(["score"], [{"score": 50}, {"score": 95}]),
    )
    assert out[0]["fired"] is True


def test_column_expression_all_rows_fails_when_one_row_short():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [
            {
                "type": "column_expression",
                "column": "score",
                "operator": "gt",
                "value": 90,
                "scope": "all_rows",
            }
        ],
        _result(["score"], [{"score": 50}, {"score": 95}]),
    )
    assert out[0]["fired"] is False


def test_column_expression_missing_column():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [
            {
                "type": "column_expression",
                "column": "missing",
                "operator": "gt",
                "value": 0,
                "scope": "any_row",
            }
        ],
        _result(["score"], [{"score": 50}]),
    )
    assert out[0]["fired"] is False


def test_column_expression_empty_result():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [
            {
                "type": "column_expression",
                "column": "score",
                "operator": "gt",
                "value": 0,
                "scope": "any_row",
            }
        ],
        _result(["score"], []),
    )
    assert out[0]["fired"] is False


def test_unknown_trigger_type_does_not_fire():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "slope", "operator": "gt", "value": 0.5}],
        _result(["n"], [{"n": 1}]),
    )
    # slope is gone; unknown types simply don't fire.
    assert out[0]["fired"] is False
    assert "Unknown trigger type" in out[0]["message"]


def test_list_of_list_row_shape_supported():
    ev = TriggerEvaluator()
    out = ev.evaluate(
        [{"type": "threshold", "operator": "gt", "value": 10, "column": "n"}],
        _result(["n"], [[42]]),
    )
    assert out[0]["fired"] is True


def test_any_fired_helper():
    ev = TriggerEvaluator()
    assert ev.any_fired([{"fired": False}, {"fired": True}]) is True
    assert ev.any_fired([{"fired": False}]) is False
    assert ev.any_fired([]) is False
