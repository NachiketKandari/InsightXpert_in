"""Text-to-SQL pipeline: Stage Protocol + default orchestrator."""

from .pipeline import Pipeline
from .stage import PipelineContext, Stage

__all__ = ["Pipeline", "PipelineContext", "Stage"]
