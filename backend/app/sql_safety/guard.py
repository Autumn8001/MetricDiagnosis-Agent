"""Static SQL AST Guard based on sqlglot PostgreSQL dialect."""

from collections.abc import Collection
from dataclasses import dataclass
import re

import sqlglot
from sqlglot import exp


class SqlGuardError(Exception):
    """Base exception for all SQL Guard validation failures."""


@dataclass(frozen=True)
class ValidatedSql:
    """Immutable validated SQL representation.

    Attributes:
        sql: Regenerated PostgreSQL dialect SQL string.
        referenced_tables: Normalized, deduplicated, and sorted tuple of schema.table names.
        effective_limit: Enforced integer LIMIT on the query.
    """

    sql: str
    referenced_tables: tuple[str, ...]
    effective_limit: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "referenced_tables", tuple(self.referenced_tables))


# Safe analytical functions permitted in SELECT queries (unqualified built-in only)
SAFE_FUNCTION_ALLOWLIST: frozenset[str] = frozenset(
    {"SUM", "COUNT", "AVG", "MIN", "MAX", "NULLIF", "COALESCE", "ABS"}
)

# Standard allowed language constructs that inherit from exp.Func in sqlglot
SYNTAX_CONSTRUCT_NODES = (
    exp.Case,
    exp.If,
    exp.Cast,
    exp.TryCast,
)

_TABLE_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$")


class SqlGuard:
    """Deterministic static SQL safety validator driven by AST analysis."""

    def __init__(
        self,
        allowed_tables: Collection[str],
        max_rows: int = 1000,
    ) -> None:
        """Initialize SqlGuard with an allowlist of schema-qualified tables and max_rows limit.

        Args:
            allowed_tables: Non-empty collection of 'schema.table' strings.
            max_rows: Positive integer maximum rows limit.
        """
        if not allowed_tables:
            raise SqlGuardError("allowed_tables cannot be empty")

        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows <= 0:
            raise SqlGuardError(f"max_rows must be a positive integer, got {max_rows}")

        normalized_tables: set[str] = set()
        for t in allowed_tables:
            if not isinstance(t, str) or not _TABLE_NAME_PATTERN.match(t.strip()):
                raise SqlGuardError(
                    f"Invalid table name in allowlist: '{t}'. Must be in 'schema.table' format."
                )
            normalized_tables.add(t.strip().lower())

        self._allowed_tables: frozenset[str] = frozenset(normalized_tables)
        self._max_rows: int = max_rows

    @property
    def allowed_tables(self) -> frozenset[str]:
        """Return the immutable set of allowed tables."""
        return self._allowed_tables

    @property
    def max_rows(self) -> int:
        """Return the maximum allowed rows."""
        return self._max_rows

    def validate(self, sql_text: str) -> ValidatedSql:
        """Validate and sanitize a raw SQL query against security invariants.

        Args:
            sql_text: Raw SQL query string.

        Returns:
            ValidatedSql with sanitized SQL string, table references, and effective limit.

        Raises:
            SqlGuardError: If any security check, syntax validation, or allowlist check fails.
        """
        if not isinstance(sql_text, str) or not sql_text.strip():
            raise SqlGuardError("SQL text cannot be empty or blank")

        try:
            parsed_list = sqlglot.parse(
                sql_text, read="postgres", error_level=sqlglot.ErrorLevel.RAISE
            )
        except Exception as e:
            raise SqlGuardError(f"SQL parsing failed: {e}") from e

        valid_stmts = [s for s in parsed_list if s is not None]
        if not valid_stmts:
            raise SqlGuardError("No valid SQL statements found")
        if len(valid_stmts) > 1:
            raise SqlGuardError(
                f"Multiple statements are not allowed, found {len(valid_stmts)} statements"
            )

        stmt = valid_stmts[0]

        if hasattr(stmt, "errors") and stmt.errors:
            raise SqlGuardError(f"SQL syntax error: {stmt.errors}")

        # 1. Restrict Top-Level Statement Type (Only SELECT)
        if not isinstance(stmt, exp.Select):
            stmt_type = type(stmt).__name__
            raise SqlGuardError(
                f"Only single SELECT statements are allowed, got {stmt_type}"
            )

        # Must have select projection expressions
        if not stmt.expressions:
            raise SqlGuardError("SELECT query must specify at least one projected column or expression")

        # 2. Reject Dangerous Clauses & AST Constructs
        # CTE / WITH
        if stmt.args.get("with") is not None or any(stmt.find_all(exp.With)):
            raise SqlGuardError("CTE / WITH queries are not allowed")

        # Set operations (UNION, INTERSECT, EXCEPT)
        if isinstance(stmt, (exp.Union, exp.Intersect, exp.Except)) or any(
            stmt.find_all((exp.Union, exp.Intersect, exp.Except))
        ):
            raise SqlGuardError("UNION, INTERSECT, and EXCEPT set operations are not allowed")

        # SELECT INTO
        if stmt.args.get("into") is not None or any(stmt.find_all(exp.Into)):
            raise SqlGuardError("SELECT INTO is not allowed")

        # Locks (FOR UPDATE, FOR SHARE, etc.)
        if stmt.args.get("locks") or any(stmt.find_all(exp.Lock)):
            raise SqlGuardError("Locking clauses (FOR UPDATE / FOR SHARE) are not allowed")

        # Must have a table FROM clause
        if stmt.find(exp.From) is None:
            raise SqlGuardError("Queries without a FROM clause are not allowed")

        # Custom PostgreSQL operators: OPERATOR(...)
        if any(stmt.find_all(exp.Operator)):
            raise SqlGuardError("Custom OPERATOR expressions are not allowed")

        # Table sampling: TABLESAMPLE ...
        if any(stmt.find_all(exp.TableSample)):
            raise SqlGuardError("TABLESAMPLE clauses are not allowed")

        # Offset: OFFSET ...
        if stmt.args.get("offset") is not None or any(stmt.find_all(exp.Offset)):
            raise SqlGuardError("OFFSET clauses are not allowed in v1 query subset")

        # Window functions: OVER (...)
        if any(stmt.find_all(exp.Window)):
            raise SqlGuardError("Window functions and OVER clauses are not allowed")

        # Interval expressions
        if any(stmt.find_all(exp.Interval)):
            raise SqlGuardError("INTERVAL expressions are not allowed in v1 query subset")

        # 3. Table Allowlist Check (Traverse all tables across main query, joins, subqueries)
        table_nodes = list(stmt.find_all(exp.Table))
        if not table_nodes:
            raise SqlGuardError("Query must reference at least one schema-qualified table")

        referenced_tables_set: set[str] = set()
        for t_node in table_nodes:
            if t_node.catalog:
                raise SqlGuardError(
                    f"3-part table names (catalog.schema.table) are not allowed: '{t_node.sql(dialect='postgres')}'"
                )
            if not t_node.db:
                raise SqlGuardError(
                    f"Table name must be schema-qualified (e.g. schema.table), got '{t_node.name}'"
                )

            qualified_name = f"{t_node.db.lower()}.{t_node.name.lower()}"
            if qualified_name not in self._allowed_tables:
                raise SqlGuardError(
                    f"Table '{qualified_name}' is not in allowed tables: {sorted(self._allowed_tables)}"
                )
            referenced_tables_set.add(qualified_name)

        referenced_tables = tuple(sorted(referenced_tables_set))

        # 4. Function Allowlist Check
        for f_node in stmt.find_all(exp.Func):
            if isinstance(f_node, SYNTAX_CONSTRUCT_NODES):
                continue

            # Reject schema-qualified functions (e.g. evil.sum(...), public.abs(...))
            if isinstance(f_node.parent, exp.Dot):
                raise SqlGuardError(
                    f"Schema-qualified function calls are not allowed: '{f_node.parent.sql(dialect='postgres')}'"
                )

            if isinstance(f_node, exp.Anonymous):
                func_name = f_node.name.upper()
            else:
                func_name = f_node.sql_name().upper()

            if func_name not in SAFE_FUNCTION_ALLOWLIST:
                raise SqlGuardError(
                    f"Function '{func_name}' is not in allowed safe functions: {sorted(SAFE_FUNCTION_ALLOWLIST)}"
                )

        # 5. LIMIT Enforcement
        limit_node = stmt.args.get("limit")
        if limit_node is None:
            effective_limit = self._max_rows
            stmt = stmt.limit(self._max_rows)
        else:
            val_exp = limit_node.expression
            if not (isinstance(val_exp, exp.Literal) and val_exp.is_int):
                raise SqlGuardError(
                    f"LIMIT must be a positive integer literal, got '{limit_node.sql(dialect='postgres')}'"
                )
            limit_val = int(val_exp.this)
            if limit_val <= 0:
                raise SqlGuardError(f"LIMIT must be a positive integer (> 0), got {limit_val}")
            if limit_val > self._max_rows:
                raise SqlGuardError(
                    f"LIMIT {limit_val} exceeds maximum allowed rows ({self._max_rows})"
                )
            effective_limit = limit_val

        sanitized_sql = stmt.sql(dialect="postgres")

        return ValidatedSql(
            sql=sanitized_sql,
            referenced_tables=referenced_tables,
            effective_limit=effective_limit,
        )
