from abc import ABC, abstractmethod

from insightxpert_api.vendored.pipeline_core.models.query import CandidateSQL, QueryRequest, QueryResult, RefinedSQL


class BaseRefiner(ABC):
    @abstractmethod
    def refine(
        self,
        request: QueryRequest,
        candidate: CandidateSQL,
        result: QueryResult,
        schema_text: str,
        db_id: str,
    ) -> RefinedSQL:
        """Fix candidate SQL using execution feedback.

        Must always return RefinedSQL. Never raises — catches all internal exceptions.
        If no fix needed or possible: return RefinedSQL(sql=candidate.sql, iterations=0).
        """
        ...
