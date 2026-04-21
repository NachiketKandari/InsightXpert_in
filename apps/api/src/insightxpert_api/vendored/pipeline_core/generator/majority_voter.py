"""Majority voting across multiple SQL candidate results."""
import logging
from collections import defaultdict

from pydantic import BaseModel

from insightxpert_api.vendored.pipeline_core.models.query import CandidateSQL, QueryResult

logger = logging.getLogger(__name__)


class VoteResult(BaseModel):
    """Result of majority voting across candidates."""
    winner_index: int
    group_sizes: list[int]
    vote_method: str  # "majority" | "fallback_first"


class MajorityVoter:
    """Pick the SQL candidate whose result set is agreed upon by the most candidates."""

    def vote(
        self,
        candidates: list[CandidateSQL],
        results: list[QueryResult],
    ) -> VoteResult:
        """Vote on candidates by grouping identical result sets.

        Error results are placed in a separate group that cannot win.
        Ties are broken by preferring the lowest candidate index.
        """
        # Group by result set (frozenset of row tuples)
        groups: dict[frozenset, list[int]] = defaultdict(list)
        error_indices: list[int] = []

        for i, result in enumerate(results):
            if result.error:
                error_indices.append(i)
                continue
            key = frozenset(tuple(r) for r in result.rows)
            groups[key].append(i)

        if not groups:
            # All candidates errored — fall back to first
            logger.warning("All %d candidates produced errors, falling back to first", len(candidates))
            return VoteResult(
                winner_index=0,
                group_sizes=[1] * len(candidates),
                vote_method="fallback_first",
            )

        # Find the largest group; ties broken by lowest index in group
        best_key = max(groups, key=lambda k: (len(groups[k]), -min(groups[k])))
        winner_index = min(groups[best_key])
        group_sizes = sorted((len(indices) for indices in groups.values()), reverse=True)

        method = "majority" if group_sizes[0] > 1 else "fallback_first"
        logger.info(
            "Majority vote: %d groups, sizes=%s, winner=candidate[%d] (%s)",
            len(groups), group_sizes, winner_index, method,
        )
        return VoteResult(
            winner_index=winner_index,
            group_sizes=group_sizes,
            vote_method=method,
        )
