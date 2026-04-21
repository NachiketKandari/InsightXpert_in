"""Generate a consolidated, database-level evidence reference from per-question hints."""
import logging
from pathlib import Path

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)

_UNIFIED_EVIDENCE_FILENAME = "unified_evidence.txt"


def unified_evidence_path(db_id: str, profiles_base_dir: Path | None = None) -> Path:
    base = (profiles_base_dir or settings.profiles_dir)
    return base / db_id / _UNIFIED_EVIDENCE_FILENAME


def load_unified_evidence(db_id: str, profiles_base_dir: Path | None = None) -> str:
    """Load stored unified evidence for a database. Returns empty string if not generated yet."""
    path = unified_evidence_path(db_id, profiles_base_dir)
    if not path.exists():
        return ""
    return path.read_text().strip()


class EvidenceUnifier:
    """Consolidates per-question evidence hints into a single database-level reference."""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm
        self._template = settings.get_jinja_env().get_template("unify_evidence.j2")

    def generate(
        self,
        db_id: str,
        evidences: list[str],
        schema: DatabaseSchema,
        profile: DatabaseProfile,
    ) -> str:
        """Call the LLM to consolidate evidences and return the unified reference text.

        Deduplicates and strips blank evidences before sending.
        Saves result to profiles/{db_id}/unified_evidence.txt.
        """
        unique = sorted({e.strip() for e in evidences if e.strip()})
        if not unique:
            logger.warning("No non-empty evidences found for '%s' — nothing to unify", db_id)
            return ""

        logger.info(
            "Unifying %d unique evidences for '%s' via LLM...", len(unique), db_id
        )

        # No JoinGraph here — evidence unification runs during profile generation
        # before join_graph.json exists; hubs only affect prompts at query time.
        schema_text = SchemaFormatter().format(schema, profile)
        prompt = self._template.render(
            db_id=db_id,
            evidences=unique,
            evidence_count=len(unique),
            schema_text=schema_text,
        )

        logger.debug("Unify evidence prompt:\n%s", prompt)
        result = self._llm.generate(prompt).strip()
        logger.debug("Unify evidence response:\n%s", result)

        out_path = unified_evidence_path(db_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result)
        logger.info("Unified evidence saved to %s", out_path)

        return result
