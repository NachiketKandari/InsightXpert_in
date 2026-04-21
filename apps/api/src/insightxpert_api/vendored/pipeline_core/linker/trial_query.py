"""Generate trial SQL from a schema variant and extract referenced fields."""
import logging
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)


@dataclass
class ExtractedFields:
    """Fields extracted from a single trial SQL query."""
    tables: set[str] = field(default_factory=set)
    columns: set[tuple[str, str]] = field(default_factory=set)  # (table, column); table="" if unqualified
    literals: set[str] = field(default_factory=set)
    sql: str = ""


class TrialQueryGenerator:
    """Generate a trial SQL for one schema variant and parse it with sqlglot."""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm
        self._template = settings.get_jinja_env().get_template("trial_query.j2")

    def generate_and_extract(
        self,
        question: str,
        evidence: str,
        schema_text: str,
        variant_name: str,
    ) -> ExtractedFields:
        """Generate trial SQL and extract tables, columns, and literals.

        Returns empty ExtractedFields on any failure — schema linking must be
        fault-tolerant; a single variant failure should not abort the whole process.
        """
        try:
            sql = self._generate_sql(question, evidence, schema_text)
        except Exception as e:
            logger.warning("Trial SQL generation failed for variant '%s': %s", variant_name, e)
            return ExtractedFields()

        extracted = self._parse_fields(sql)
        extracted.sql = sql
        logger.info(
            "Variant '%s': %d tables, %d columns, %d literals",
            variant_name,
            len(extracted.tables),
            len(extracted.columns),
            len(extracted.literals),
        )
        return extracted

    def revise_and_extract(
        self,
        question: str,
        evidence: str,
        schema_text: str,
        previous_sql: str,
        literal_candidates: dict[str, list[str]],
        variant_name: str,
        literal_values: dict[str, dict[str, list[str]]] | None = None,
    ) -> ExtractedFields:
        """Re-prompt the LLM to revise trial SQL when literals don't match column values.

        Args:
            literal_values: optional mapping of literal -> { "table.column": [actual_values] }
                from LSH. When provided, the revision prompt shows concrete DB values.

        Returns empty ExtractedFields on failure (fault-tolerant).
        """
        if not hasattr(self, "_revision_template"):
            self._revision_template = settings.get_jinja_env().get_template(
                "trial_query_revision.j2"
            )
        try:
            prompt = self._revision_template.render(
                question=question,
                evidence=evidence,
                schema_text=schema_text,
                previous_sql=previous_sql,
                literal_candidates=literal_candidates,
                literal_values=literal_values or {},
            )
            raw = self._llm.generate(prompt)
            sql = self._extract_sql(raw)
        except Exception as e:
            logger.warning(
                "Trial SQL revision failed for variant '%s': %s", variant_name, e
            )
            return ExtractedFields()

        extracted = self._parse_fields(sql)
        extracted.sql = sql
        logger.info(
            "Variant '%s' revision: %d tables, %d columns, %d literals",
            variant_name,
            len(extracted.tables),
            len(extracted.columns),
            len(extracted.literals),
        )
        return extracted

    def _generate_sql(self, question: str, evidence: str, schema_text: str) -> str:
        prompt = self._template.render(
            question=question,
            evidence=evidence,
            schema_text=schema_text,
        )
        logger.debug("Trial query prompt:\n%s", prompt)
        raw = self._llm.generate(prompt)
        logger.debug("Trial query raw response:\n%s", raw)
        return self._extract_sql(raw)

    def _extract_sql(self, raw: str) -> str:
        match = _FENCE_RE.search(raw)
        if match:
            sql = match.group(1).strip()
        else:
            logger.warning("No fenced code block in trial query response; using full response")
            sql = raw.strip()

        sql = sql.rstrip(";").strip()

        if ";" in sql:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt.upper().startswith("SELECT"):
                    return stmt
        return sql

    @staticmethod
    def _parse_fields(sql: str) -> ExtractedFields:
        """Parse SQL with sqlglot and extract tables, columns, and string literals."""
        if not sql:
            return ExtractedFields()

        try:
            parsed = sqlglot.parse_one(sql, read="sqlite")
        except sqlglot.errors.SqlglotError:
            logger.warning("sqlglot failed to parse trial SQL: %.120s", sql)
            return ExtractedFields()

        # Build alias map: alias_name -> real table name
        alias_map: dict[str, str] = {}
        for table_node in parsed.find_all(exp.Table):
            alias = table_node.alias
            if alias:
                alias_map[alias] = table_node.name

        # Extract tables
        tables: set[str] = {t.name for t in parsed.find_all(exp.Table) if t.name}

        # Extract columns, resolving aliases
        columns: set[tuple[str, str]] = set()
        for col in parsed.find_all(exp.Column):
            col_name = col.name
            if not col_name:
                continue
            table_ref = col.table or ""
            real_table = alias_map.get(table_ref, table_ref)
            columns.add((real_table, col_name))

        # Extract string literals
        literals: set[str] = {
            lit.this for lit in parsed.find_all(exp.Literal) if lit.is_string and lit.this
        }

        return ExtractedFields(tables=tables, columns=columns, literals=literals)
