"""Compare two or more evaluation result files to find unions, intersections, and deltas."""

import json
import logging
from itertools import combinations
from pathlib import Path
from typing import Any

from insightxpert_api.vendored.pipeline_core.models.evaluation import EvalReport, EvalResult

logger = logging.getLogger(__name__)


def _load_report(path: Path) -> EvalReport:
    """Load an EvalReport from a JSON file."""
    with path.open() as f:
        data = json.load(f)
    return EvalReport.model_validate(data)


def _run_label(path: Path) -> str:
    """Derive a short label from the results directory name."""
    return path.parent.name


def _pct(num: int, den: int) -> str:
    """Format a percentage with one decimal, handling zero denominator."""
    return f"{num / den * 100:.1f}%" if den else "N/A"


def _frac(num: int, den: int) -> str:
    """Format as 'num/den (pct%)'."""
    return f"{num}/{den} ({_pct(num, den)})"


def compare_reports(path_a: Path, path_b: Path) -> dict[str, Any]:
    """Compare two eval result files and return a structured diff.

    Returns a dict with:
      - summary: high-level accuracy comparison (EX, EX_relaxed)
      - a_only_correct: questions A got right but B got wrong
      - b_only_correct: questions B got right but A got wrong
      - both_correct: questions both got right
      - both_wrong: questions both got wrong
      - by_difficulty: breakdown with per-side EX scores
      - by_database: breakdown with per-side EX scores
      - a_only_ids / b_only_ids: question IDs present in only one file
    """
    report_a = _load_report(path_a)
    report_b = _load_report(path_b)

    results_a = {r.question_id: r for r in report_a.results}
    results_b = {r.question_id: r for r in report_b.results}

    ids_a = set(results_a.keys())
    ids_b = set(results_b.keys())
    common_ids = ids_a & ids_b

    # Categorize common questions
    both_correct: list[dict[str, Any]] = []
    both_wrong: list[dict[str, Any]] = []
    a_only_correct: list[dict[str, Any]] = []
    b_only_correct: list[dict[str, Any]] = []

    for qid in sorted(common_ids):
        ra = results_a[qid]
        rb = results_b[qid]

        entry = {
            "question_id": qid,
            "db_id": ra.db_id,
            "question": ra.question,
            "difficulty": ra.difficulty,
            "a_predicted_sql": ra.predicted_sql,
            "b_predicted_sql": rb.predicted_sql,
            "gold_sql": ra.gold_sql,
            "a_error": ra.error,
            "b_error": rb.error,
        }

        a_ok = ra.execution_match
        b_ok = rb.execution_match

        if a_ok and b_ok:
            both_correct.append(entry)
        elif a_ok and not b_ok:
            a_only_correct.append(entry)
        elif not a_ok and b_ok:
            b_only_correct.append(entry)
        else:
            both_wrong.append(entry)

    def _build_breakdown(key_fn: Any) -> dict[str, dict[str, Any]]:
        """Build per-group breakdown with EX/EX_relaxed for both sides."""
        groups: dict[str, dict[str, Any]] = {}
        for qid in sorted(common_ids):
            ra = results_a[qid]
            rb = results_b[qid]
            key = key_fn(ra)
            if key not in groups:
                groups[key] = {
                    "total": 0,
                    "a_correct": 0, "b_correct": 0,
                    "a_correct_relaxed": 0, "b_correct_relaxed": 0,
                    "both_correct": 0, "both_wrong": 0,
                    "a_only_correct": 0, "b_only_correct": 0,
                }
            g = groups[key]
            g["total"] += 1
            if ra.execution_match:
                g["a_correct"] += 1
            if rb.execution_match:
                g["b_correct"] += 1
            if ra.execution_match_relaxed:
                g["a_correct_relaxed"] += 1
            if rb.execution_match_relaxed:
                g["b_correct_relaxed"] += 1
            a_ok = ra.execution_match
            b_ok = rb.execution_match
            if a_ok and b_ok:
                g["both_correct"] += 1
            elif a_ok:
                g["a_only_correct"] += 1
            elif b_ok:
                g["b_only_correct"] += 1
            else:
                g["both_wrong"] += 1
        return groups

    by_difficulty = _build_breakdown(lambda r: r.difficulty)
    by_database = _build_breakdown(lambda r: r.db_id)

    return {
        "summary": {
            "file_a": str(path_a),
            "file_b": str(path_b),
            "label_a": _run_label(path_a),
            "label_b": _run_label(path_b),
            "a_total": report_a.total,
            "b_total": report_b.total,
            "a_accuracy": report_a.accuracy,
            "b_accuracy": report_b.accuracy,
            "a_accuracy_relaxed": report_a.accuracy_relaxed,
            "b_accuracy_relaxed": report_b.accuracy_relaxed,
            "a_correct": report_a.correct,
            "b_correct": report_b.correct,
            "a_correct_relaxed": report_a.correct_relaxed,
            "b_correct_relaxed": report_b.correct_relaxed,
            "a_config": report_a.run_config.model_dump() if report_a.run_config else None,
            "b_config": report_b.run_config.model_dump() if report_b.run_config else None,
            "common_questions": len(common_ids),
            "a_only_questions": sorted(ids_a - ids_b),
            "b_only_questions": sorted(ids_b - ids_a),
        },
        "counts": {
            "both_correct": len(both_correct),
            "both_wrong": len(both_wrong),
            "a_only_correct": len(a_only_correct),
            "b_only_correct": len(b_only_correct),
        },
        "by_difficulty": by_difficulty,
        "by_database": by_database,
        "a_only_correct": a_only_correct,
        "b_only_correct": b_only_correct,
        "both_correct": [e["question_id"] for e in both_correct],
        "both_wrong": both_wrong,
    }


def format_comparison_text(comp: dict[str, Any]) -> str:
    """Format comparison dict as a human-readable text report."""
    lines: list[str] = []
    s = comp["summary"]
    c = comp["counts"]

    lines.append("=" * 80)
    lines.append("BENCHMARK COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"  A: {s['label_a']}")
    lines.append(f"     {s['file_a']}")
    lines.append(f"  B: {s['label_b']}")
    lines.append(f"     {s['file_b']}")
    lines.append("")

    # Config diff
    if s.get("a_config") and s.get("b_config"):
        ac, bc = s["a_config"], s["b_config"]
        diffs = [k for k in ac if ac.get(k) != bc.get(k)]
        if diffs:
            lines.append("Config differences:")
            for k in diffs:
                lines.append(f"  {k}: A={ac[k]}  B={bc[k]}")
            lines.append("")

    # Overall scores
    lines.append("-" * 80)
    lines.append(f"{'':>30}  {'A':>18}  {'B':>18}  {'Delta':>8}")
    lines.append("-" * 80)
    lines.append(
        f"{'EX (strict)':>30}  "
        f"{_frac(s['a_correct'], s['a_total']):>18}  "
        f"{_frac(s['b_correct'], s['b_total']):>18}  "
        f"{s['b_accuracy'] - s['a_accuracy']:>+7.1%}"
    )
    lines.append(
        f"{'EX (relaxed)':>30}  "
        f"{_frac(s['a_correct_relaxed'], s['a_total']):>18}  "
        f"{_frac(s['b_correct_relaxed'], s['b_total']):>18}  "
        f"{s['b_accuracy_relaxed'] - s['a_accuracy_relaxed']:>+7.1%}"
    )
    lines.append("-" * 80)
    lines.append("")

    lines.append(f"Common questions: {s['common_questions']}")
    if s["a_only_questions"]:
        lines.append(f"Only in A: {len(s['a_only_questions'])} questions")
    if s["b_only_questions"]:
        lines.append(f"Only in B: {len(s['b_only_questions'])} questions")
    lines.append("")

    lines.append(f"  Both correct:       {c['both_correct']:>4}")
    lines.append(f"  A correct, B wrong: {c['a_only_correct']:>4}")
    lines.append(f"  B correct, A wrong: {c['b_only_correct']:>4}")
    lines.append(f"  Both wrong:         {c['both_wrong']:>4}")
    net = c["b_only_correct"] - c["a_only_correct"]
    direction = "B" if net > 0 else "A" if net < 0 else "tied"
    lines.append(f"  Net delta: {abs(net)} questions favor {direction}")
    lines.append("")

    # By database — full EX table
    lines.append("BY DATABASE:")
    lines.append("-" * 80)
    lines.append(
        f"{'Database':>30}  {'A EX':>12}  {'B EX':>12}  "
        f"{'A>B':>4}  {'B>A':>4}  {'Delta':>7}"
    )
    lines.append("-" * 80)
    for db in sorted(comp["by_database"]):
        d = comp["by_database"][db]
        a_ex = d["a_correct"] / d["total"] if d["total"] else 0
        b_ex = d["b_correct"] / d["total"] if d["total"] else 0
        lines.append(
            f"{db:>30}  "
            f"{_frac(d['a_correct'], d['total']):>12}  "
            f"{_frac(d['b_correct'], d['total']):>12}  "
            f"{d['a_only_correct']:>4}  {d['b_only_correct']:>4}  "
            f"{(b_ex - a_ex) * 100:>+6.1f}pp"
        )
    lines.append("-" * 80)
    lines.append("")

    # By difficulty — full EX table
    lines.append("BY DIFFICULTY:")
    lines.append("-" * 80)
    lines.append(
        f"{'Difficulty':>30}  {'A EX':>12}  {'B EX':>12}  "
        f"{'A>B':>4}  {'B>A':>4}  {'Delta':>7}"
    )
    lines.append("-" * 80)
    for diff in ["simple", "moderate", "challenging"]:
        if diff in comp["by_difficulty"]:
            d = comp["by_difficulty"][diff]
            a_ex = d["a_correct"] / d["total"] if d["total"] else 0
            b_ex = d["b_correct"] / d["total"] if d["total"] else 0
            lines.append(
                f"{diff:>30}  "
                f"{_frac(d['a_correct'], d['total']):>12}  "
                f"{_frac(d['b_correct'], d['total']):>12}  "
                f"{d['a_only_correct']:>4}  {d['b_only_correct']:>4}  "
                f"{(b_ex - a_ex) * 100:>+6.1f}pp"
            )
    lines.append("-" * 80)
    lines.append("")

    # Details of interesting questions
    if comp["a_only_correct"]:
        lines.append(f"A GOT RIGHT, B GOT WRONG ({c['a_only_correct']} questions):")
        for e in comp["a_only_correct"]:
            lines.append(f"  Q{e['question_id']} [{e['db_id']}/{e['difficulty']}]: {e['question']}")
            if e["b_error"]:
                lines.append(f"    B error: {e['b_error'][:120]}")
        lines.append("")

    if comp["b_only_correct"]:
        lines.append(f"B GOT RIGHT, A GOT WRONG ({c['b_only_correct']} questions):")
        for e in comp["b_only_correct"]:
            lines.append(f"  Q{e['question_id']} [{e['db_id']}/{e['difficulty']}]: {e['question']}")
            if e["a_error"]:
                lines.append(f"    A error: {e['a_error'][:120]}")
        lines.append("")

    return "\n".join(lines)


def discover_result_files(
    results_dir: Path,
    prefix: str = "minidev_all_",
) -> list[Path]:
    """Find all eval result JSON files under results_dir whose parent dir matches prefix.

    When a directory contains multiple result files, picks the latest one (by filename timestamp).
    """
    found: dict[str, Path] = {}  # dir_name -> latest file
    if not results_dir.is_dir():
        return []
    for d in sorted(results_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith(prefix):
            continue
        jsons = sorted(d.glob("eval_results_*.json"))
        if jsons:
            found[d.name] = jsons[-1]  # latest by timestamp in filename
    return list(found.values())


def compare_matrix(
    files: list[Path],
    target: Path | None = None,
) -> list[dict[str, Any]]:
    """Compare multiple result files.

    If target is given, compare target vs each other file.
    If target is None, compare all pairs.

    Returns a list of comparison dicts.
    """
    if target:
        others = [f for f in files if f != target]
        pairs = [(target, other) for other in others]
    else:
        pairs = list(combinations(files, 2))

    return [compare_reports(a, b) for a, b in pairs]


def format_matrix_text(comparisons: list[dict[str, Any]]) -> str:
    """Format multiple comparisons as a summary table plus individual details."""
    if not comparisons:
        return "No comparisons to show."

    lines: list[str] = []
    lines.append("=" * 100)
    lines.append("MULTI-RUN COMPARISON MATRIX")
    lines.append("=" * 100)
    lines.append("")

    # Summary table
    lines.append(
        f"{'A (run)':>45}  {'B (run)':>45}  {'A EX':>7}  {'B EX':>7}  {'Delta':>7}"
    )
    lines.append("-" * 120)
    for comp in comparisons:
        s = comp["summary"]
        lines.append(
            f"{s['label_a']:>45}  "
            f"{s['label_b']:>45}  "
            f"{s['a_accuracy']:>6.1%}  "
            f"{s['b_accuracy']:>6.1%}  "
            f"{s['b_accuracy'] - s['a_accuracy']:>+6.1%}"
        )
    lines.append("-" * 120)
    lines.append("")

    # Individual reports
    for i, comp in enumerate(comparisons):
        lines.append(f"{'─' * 80}")
        lines.append(f"PAIR {i + 1}")
        lines.append(format_comparison_text(comp))
        lines.append("")

    return "\n".join(lines)
