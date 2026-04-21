"""Validate SQL syntax, enforce SELECT-only policy, and post-process SQL.

Includes optional semantic anti-pattern checks (Section 4 of the paper):
- ORDER BY + LIMIT 1 when MIN/MAX would be correct
- Concatenation of fields that should be returned as separate columns
"""
import logging
import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)


class SQLValidator:
    def __init__(self, dialect: str = "sqlite") -> None:
        self._dialect = dialect

    def validate(self, sql: str) -> tuple[bool, str]:
        """Return (True, "") if sql is a valid read query, else (False, reason)."""
        if not sql or not sql.strip():
            logger.debug("Validation failed: empty SQL")
            return False, "Empty SQL"

        try:
            # Parse the SQL into an AST (Abstract Syntax Tree)
            # This automatically ignores comments and formatting
            parsed_expressions = sqlglot.parse(sql, read=self._dialect)

            if not parsed_expressions or not parsed_expressions[0]:
                return False, "Could not parse SQL"

            # Check every statement in the parsed output
            for expression in parsed_expressions:
                # sqlglot treats set operations as distinct from standard Selects
                allowed_operations = (exp.Select, exp.Union, exp.Intersect, exp.Except)

                if not isinstance(expression, allowed_operations):
                    logger.debug("Validation failed: Found non-SELECT operation: %s", type(expression).__name__)
                    return False, "Only read-only statements (SELECT, UNION, INTERSECT, EXCEPT) are allowed"

            # Transpile to catch any deeper dialect-specific errors
            sqlglot.transpile(sql, read=self._dialect, write=self._dialect)

        except sqlglot.errors.ParseError as e:
            logger.warning("SQL syntax error: %s", e)
            return False, f"Syntax Error: {e}"
        except sqlglot.errors.SqlglotError as e:
            logger.warning("SQL transpilation error: %s", e)
            return False, f"Transpilation Error: {e}"

        logger.debug("Validation passed")
        return True, ""

    def fix_construction_antipatterns(self, sql: str, question: str) -> str:
        """Detect and fix semantic SQL anti-patterns from the paper (Section 4).

        Currently checks:
        1. ORDER BY col ASC/DESC LIMIT 1 → MIN(col)/MAX(col) when question asks
           for smallest/largest/highest/lowest/minimum/maximum
        2. String concatenation (||) of columns → separate SELECT columns

        Returns the (possibly rewritten) SQL string.
        """
        try:
            parsed = sqlglot.parse_one(sql, read=self._dialect)
        except sqlglot.errors.SqlglotError:
            return sql

        sql = self._fix_orderby_to_aggregate(parsed, sql, question)
        sql = self._fix_concat_to_columns(sql)
        return sql

    def _fix_orderby_to_aggregate(
        self, parsed: exp.Expression, sql: str, question: str,
    ) -> str:
        """Replace ORDER BY col LIMIT 1 with MIN/MAX(col) when appropriate.

        Pattern: SELECT col FROM ... ORDER BY col ASC LIMIT 1 → SELECT MIN(col)
                 SELECT col FROM ... ORDER BY col DESC LIMIT 1 → SELECT MAX(col)

        Only applies when the question implies an extreme value (min/max/highest/lowest).
        """
        q_lower = question.lower()
        wants_extreme = any(kw in q_lower for kw in [
            "minimum", "maximum", "smallest", "largest", "highest", "lowest",
            "most expensive", "least expensive", "cheapest", "oldest", "youngest",
            "earliest", "latest", "longest", "shortest", "greatest", "fewest",
        ])
        if not wants_extreme:
            return sql

        if not isinstance(parsed, exp.Select):
            return sql

        limit = parsed.args.get("limit")
        order = parsed.args.get("order")
        if not limit or not order:
            return sql

        # Check LIMIT 1
        limit_expr = limit.expression
        if not isinstance(limit_expr, exp.Literal) or limit_expr.this != "1":
            return sql

        order_exprs = order.expressions
        if len(order_exprs) != 1:
            return sql

        ordered = order_exprs[0]
        is_desc = ordered.args.get("desc", False)
        order_col = ordered.this

        # Check if the SELECT expression matches the ORDER BY expression
        select_exprs = parsed.expressions
        if len(select_exprs) != 1:
            return sql

        select_col = select_exprs[0]
        # Unwrap alias if present
        if isinstance(select_col, exp.Alias):
            select_col = select_col.this

        # Simple check: both reference the same column
        if select_col.sql(dialect=self._dialect) != order_col.sql(dialect=self._dialect):
            return sql

        agg_func = "MAX" if is_desc else "MIN"
        agg_expr = sqlglot.parse_one(
            f"{agg_func}({order_col.sql(dialect=self._dialect)})", read=self._dialect
        )

        # Rewrite: replace SELECT col with SELECT AGG(col), remove ORDER BY and LIMIT
        parsed.set("expressions", [agg_expr])
        parsed.set("order", None)
        parsed.set("limit", None)

        result = parsed.sql(dialect=self._dialect)
        logger.info(
            "Anti-pattern fix: ORDER BY + LIMIT 1 → %s() for %r",
            agg_func, order_col.sql(dialect=self._dialect),
        )
        return result

    def _fix_concat_to_columns(self, sql: str) -> str:
        """Replace string concatenation (||) in SELECT with separate columns.

        Pattern: SELECT col1 || ' ' || col2 → SELECT col1, col2
        Only applies when ALL select expressions are concatenations.
        """
        try:
            parsed = sqlglot.parse_one(sql, read=self._dialect)
        except sqlglot.errors.SqlglotError:
            return sql

        if not isinstance(parsed, exp.Select):
            return sql

        select_exprs = parsed.expressions
        if not select_exprs:
            return sql

        # Check if any expression contains DPipe (||) concatenation
        has_concat = any(expr.find(exp.DPipe) for expr in select_exprs)
        if not has_concat:
            return sql

        new_exprs: list[exp.Expression] = []
        changed = False
        for expr in select_exprs:
            # Unwrap alias
            inner = expr.this if isinstance(expr, exp.Alias) else expr
            if inner.find(exp.DPipe):
                # Extract real column references (skip string literals parsed as quoted identifiers)
                columns = [
                    node for node in inner.find_all(exp.Column)
                    if not (hasattr(node.this, "quoted") and node.this.quoted
                            and node.this.this.strip() in ("", " ", ", ", " - ", " | "))
                    and not node.this.quoted
                ]
                if len(columns) >= 2:
                    new_exprs.extend(columns)
                    changed = True
                else:
                    new_exprs.append(expr)
            else:
                new_exprs.append(expr)

        if not changed:
            return sql

        parsed.set("expressions", new_exprs)
        result = parsed.sql(dialect=self._dialect)
        logger.info("Anti-pattern fix: concatenation → %d separate columns", len(new_exprs))
        return result