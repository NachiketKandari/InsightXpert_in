"""Aggregate evaluation results and emit a summary report."""
import logging

from insightxpert_api.vendored.pipeline_core.models.evaluation import EvalReport, EvalResult

logger = logging.getLogger(__name__)

# Gemini 3.1 Flash Lite Preview pricing (USD per million tokens)
_PRICING: dict[str, tuple[float, float]] = {
    # model_substring: (input_per_M, output_per_M)
    "flash-lite": (0.25, 1.50),
    "flash": (0.15, 0.60),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku": (0.80, 4.00),
    "claude-opus": (15.00, 75.00),
}
_DEFAULT_PRICING = (0.25, 1.50)  # fallback to flash-lite


class EvalReporter:
    def report(self, results: list[EvalResult]) -> EvalReport:
        """Aggregate results into an EvalReport with overall and per-difficulty metrics."""
        total = len(results)
        correct = sum(1 for r in results if r.execution_match)
        accuracy = correct / total if total else 0.0
        correct_relaxed = sum(1 for r in results if r.execution_match_relaxed)
        accuracy_relaxed = correct_relaxed / total if total else 0.0

        # Group by difficulty using question_id lookup from results
        by_difficulty: dict[str, dict[str, int]] = {}
        for r in results:
            diff = getattr(r, "difficulty", "simple")
            bucket = by_difficulty.setdefault(diff, {"total": 0, "correct": 0, "correct_relaxed": 0})
            bucket["total"] += 1
            if r.execution_match:
                bucket["correct"] += 1
            if r.execution_match_relaxed:
                bucket["correct_relaxed"] += 1

        return EvalReport(
            total=total,
            correct=correct,
            accuracy=accuracy,
            correct_relaxed=correct_relaxed,
            accuracy_relaxed=accuracy_relaxed,
            by_difficulty=by_difficulty,
            results=results,
        )

    @staticmethod
    def estimate_cost(
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> float:
        """Estimate USD cost based on token counts and model pricing."""
        input_rate, output_rate = _DEFAULT_PRICING
        for key, rates in _PRICING.items():
            if key in model.lower():
                input_rate, output_rate = rates
                break
        return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate

    def log_report(self, report: EvalReport) -> None:
        """Emit the evaluation summary via logger.info."""
        logger.info("=== Evaluation Report ===")
        logger.info(
            "Strict: %d/%d = %.1f%% | Relaxed: %d/%d = %.1f%%",
            report.correct,
            report.total,
            report.accuracy * 100,
            report.correct_relaxed,
            report.total,
            report.accuracy_relaxed * 100,
        )

        if report.by_difficulty:
            logger.info("By Difficulty:")
            for diff in ("simple", "moderate", "challenging"):
                if diff not in report.by_difficulty:
                    continue
                bucket = report.by_difficulty[diff]
                t = bucket["total"]
                c = bucket["correct"]
                cr = bucket.get("correct_relaxed", c)
                pct = (c / t * 100) if t else 0.0
                pct_r = (cr / t * 100) if t else 0.0
                logger.info("  %-12s %d/%d (%.1f%%) | relaxed: %d/%d (%.1f%%)", f"{diff}:", c, t, pct, cr, t, pct_r)

        if report.total_input_tokens or report.total_output_tokens:
            logger.info(
                "Tokens: %s input + %s output = %s total | Cost: $%.4f",
                f"{report.total_input_tokens:,}",
                f"{report.total_output_tokens:,}",
                f"{report.total_input_tokens + report.total_output_tokens:,}",
                report.estimated_cost_usd,
            )
