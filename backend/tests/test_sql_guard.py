"""Unit tests for SqlGuard AST security validator."""

import unittest

from app.sql_safety import SqlGuard, SqlGuardError, ValidatedSql


class TestSqlGuard(unittest.TestCase):
    """Test suite verifying SqlGuard AST safety validation rules and invariants."""

    def setUp(self) -> None:
        self.allowed_tables = [
            "warehouse.fact_daily_performance",
            "warehouse.dim_products",
        ]
        self.guard = SqlGuard(allowed_tables=self.allowed_tables, max_rows=1000)

    # -------------------------------------------------------------------------
    # Constructor & Configuration Tests
    # -------------------------------------------------------------------------
    def test_constructor_empty_allowed_tables_raises(self) -> None:
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=[])

    def test_constructor_invalid_table_format_raises(self) -> None:
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=["unqualified_table"])
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=["catalog.schema.table"])
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=["schema."])

    def test_constructor_invalid_max_rows_raises(self) -> None:
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=self.allowed_tables, max_rows=0)
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=self.allowed_tables, max_rows=-10)
        with self.assertRaises(SqlGuardError):
            SqlGuard(allowed_tables=self.allowed_tables, max_rows=True)  # type: ignore[arg-type]

    # -------------------------------------------------------------------------
    # Valid Query Tests
    # -------------------------------------------------------------------------
    def test_valid_single_table_select(self) -> None:
        sql = "SELECT marketplace, sales FROM warehouse.fact_daily_performance WHERE date = '2026-01-31'"
        result = self.guard.validate(sql)

        self.assertIsInstance(result, ValidatedSql)
        self.assertEqual(result.referenced_tables, ("warehouse.fact_daily_performance",))
        self.assertEqual(result.effective_limit, 1000)
        self.assertIn("LIMIT 1000", result.sql)

    def test_valid_join_query(self) -> None:
        sql = """
        SELECT
            f.marketplace,
            f.asin,
            p.category,
            SUM(f.sales) AS total_sales
        FROM warehouse.fact_daily_performance AS f
        JOIN warehouse.dim_products AS p ON f.asin = p.asin
        WHERE f.date = '2026-01-31'
        GROUP BY f.marketplace, f.asin, p.category
        HAVING SUM(f.sales) > 100
        ORDER BY total_sales DESC
        LIMIT 50
        """
        result = self.guard.validate(sql)

        self.assertEqual(
            result.referenced_tables,
            ("warehouse.dim_products", "warehouse.fact_daily_performance"),
        )
        self.assertEqual(result.effective_limit, 50)
        self.assertIn("LIMIT 50", result.sql)

    def test_valid_allowed_functions_and_constructs(self) -> None:
        sql = """
        SELECT
            COUNT(DISTINCT asin) AS cnt,
            SUM(sales) AS total_sales,
            AVG(sales) AS avg_sales,
            MIN(sales) AS min_sales,
            MAX(sales) AS max_sales,
            NULLIF(orders, 0) AS safe_orders,
            COALESCE(sessions, 0) AS safe_sess,
            ABS(sales) AS abs_sales,
            CAST(sales AS numeric) AS num_sales,
            CASE WHEN sales > 0 THEN 1 ELSE 0 END AS has_sales
        FROM warehouse.fact_daily_performance
        """
        result = self.guard.validate(sql)
        self.assertEqual(result.effective_limit, 1000)
        self.assertIsInstance(result.referenced_tables, tuple)

    def test_valid_subquery_with_allowed_tables(self) -> None:
        sql = """
        SELECT marketplace, total_sales
        FROM (
            SELECT marketplace, SUM(sales) AS total_sales
            FROM warehouse.fact_daily_performance
            GROUP BY marketplace
        ) AS sub
        """
        result = self.guard.validate(sql)
        self.assertEqual(result.referenced_tables, ("warehouse.fact_daily_performance",))

    def test_validated_sql_immutability(self) -> None:
        result = self.guard.validate("SELECT * FROM warehouse.dim_products")
        self.assertIsInstance(result.referenced_tables, tuple)
        with self.assertRaises(AttributeError):
            result.sql = "MUTATED"  # type: ignore[misc]

    # -------------------------------------------------------------------------
    # Rejection: Basic & Syntax Errors
    # -------------------------------------------------------------------------
    def test_reject_empty_or_whitespace_sql(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("   \n\t  ")

    def test_reject_syntax_error(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT FROM warehouse.dim_products")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("INVALID SQL SYNTAX")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM ((((")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products WHERE")

    def test_reject_multiple_statements(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT * FROM warehouse.dim_products; SELECT * FROM warehouse.fact_daily_performance"
            )
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT * FROM warehouse.dim_products; DROP TABLE warehouse.dim_products"
            )

    # -------------------------------------------------------------------------
    # Rejection: Non-SELECT DML, DDL & System Commands
    # -------------------------------------------------------------------------
    def test_reject_dml_statements(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "INSERT INTO warehouse.dim_products (asin) VALUES ('ASIN-X')"
            )
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "UPDATE warehouse.dim_products SET category = 'X' WHERE asin = 'ASIN-A'"
            )
        with self.assertRaises(SqlGuardError):
            self.guard.validate("DELETE FROM warehouse.dim_products")

    def test_reject_ddl_and_maintenance_statements(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("DROP TABLE warehouse.dim_products")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("CREATE TABLE warehouse.test (id int)")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("ALTER TABLE warehouse.dim_products ADD COLUMN col int")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("TRUNCATE TABLE warehouse.dim_products")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("EXPLAIN SELECT * FROM warehouse.dim_products")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SET statement_timeout = 1000")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SHOW statement_timeout")

    # -------------------------------------------------------------------------
    # Rejection: Dangerous SELECT Variants & AST Constructs
    # -------------------------------------------------------------------------
    def test_reject_cte_with_query(self) -> None:
        sql = "WITH cte AS (SELECT asin FROM warehouse.dim_products) SELECT * FROM cte"
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate(sql)
        self.assertIn("WITH", str(ctx.exception))

    def test_reject_set_operations(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT asin FROM warehouse.dim_products UNION SELECT asin FROM warehouse.fact_daily_performance"
            )
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT asin FROM warehouse.dim_products INTERSECT SELECT asin FROM warehouse.fact_daily_performance"
            )
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT asin FROM warehouse.dim_products EXCEPT SELECT asin FROM warehouse.fact_daily_performance"
            )

    def test_reject_select_into(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * INTO new_table FROM warehouse.dim_products")

    def test_reject_locks(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products FOR UPDATE")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products FOR SHARE")

    def test_reject_no_from_clause(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT 1")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT version()")

    # -------------------------------------------------------------------------
    # Rejection: Table Allowlist Violations
    # -------------------------------------------------------------------------
    def test_reject_unqualified_table_name(self) -> None:
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate("SELECT * FROM dim_products")
        self.assertIn("schema-qualified", str(ctx.exception))

    def test_reject_catalog_three_part_table_name(self) -> None:
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate("SELECT * FROM mydb.warehouse.dim_products")
        self.assertIn("3-part", str(ctx.exception))

    def test_reject_disallowed_application_table(self) -> None:
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate("SELECT * FROM app.evidence")
        self.assertIn("not in allowed tables", str(ctx.exception))

    def test_reject_system_catalog_tables(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM pg_catalog.pg_user")
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM information_schema.tables")

    def test_reject_disallowed_table_in_join(self) -> None:
        sql = """
        SELECT f.* FROM warehouse.fact_daily_performance f
        JOIN public.users u ON f.marketplace = u.marketplace
        """
        with self.assertRaises(SqlGuardError):
            self.guard.validate(sql)

    def test_reject_disallowed_table_in_subquery(self) -> None:
        sql = """
        SELECT * FROM warehouse.fact_daily_performance
        WHERE asin IN (SELECT asin FROM pg_catalog.pg_tables)
        """
        with self.assertRaises(SqlGuardError):
            self.guard.validate(sql)

    # -------------------------------------------------------------------------
    # Rejection: Function Allowlist Violations
    # -------------------------------------------------------------------------
    def test_reject_dangerous_and_unknown_functions(self) -> None:
        dangerous_queries = [
            "SELECT pg_sleep(5) FROM warehouse.dim_products",
            "SELECT nextval('seq') FROM warehouse.dim_products",
            "SELECT setval('seq', 1) FROM warehouse.dim_products",
            "SELECT set_config('a', 'b', false) FROM warehouse.dim_products",
            "SELECT pg_read_file('/etc/passwd') FROM warehouse.dim_products",
            "SELECT lo_import('/etc/passwd') FROM warehouse.dim_products",
            "SELECT version() FROM warehouse.dim_products",
            "SELECT now() FROM warehouse.dim_products",
            "SELECT CURRENT_TIMESTAMP FROM warehouse.dim_products",
            "SELECT custom_unknown_fn(sales) FROM warehouse.fact_daily_performance",
        ]
        for q in dangerous_queries:
            with self.subTest(query=q):
                with self.assertRaises(SqlGuardError):
                    self.guard.validate(q)

    def test_reject_schema_qualified_functions(self) -> None:
        """Verify schema-qualified functions (e.g. evil.sum, public.abs) are strictly rejected."""
        qualified_queries = [
            "SELECT evil.sum(sales) FROM warehouse.fact_daily_performance",
            "SELECT public.abs(sales) FROM warehouse.fact_daily_performance",
            "SELECT pg_catalog.sum(sales) FROM warehouse.fact_daily_performance",
        ]
        for q in qualified_queries:
            with self.subTest(query=q):
                with self.assertRaises(SqlGuardError) as ctx:
                    self.guard.validate(q)
                self.assertIn("Schema-qualified function", str(ctx.exception))

    def test_reject_custom_operators(self) -> None:
        """Verify custom PostgreSQL operators via OPERATOR(...) are rejected."""
        sql = "SELECT sales OPERATOR(evil.+) 1 FROM warehouse.fact_daily_performance"
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate(sql)
        self.assertIn("Custom OPERATOR", str(ctx.exception))

    def test_reject_tablesample_and_offset(self) -> None:
        """Verify TABLESAMPLE and OFFSET clauses are rejected in v1 subset."""
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate(
                "SELECT * FROM warehouse.fact_daily_performance TABLESAMPLE SYSTEM (100)"
            )
        self.assertIn("TABLESAMPLE", str(ctx.exception))

        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate(
                "SELECT * FROM warehouse.fact_daily_performance LIMIT 1 OFFSET 100"
            )
        self.assertIn("OFFSET", str(ctx.exception))

    def test_reject_window_functions_and_unauthorized_constructs(self) -> None:
        """Verify Window functions (OVER) and unallowed constructs (EXTRACT, INTERVAL, COLLATE) are rejected."""
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate(
                "SELECT SUM(sales) OVER () FROM warehouse.fact_daily_performance"
            )
        self.assertIn("Window", str(ctx.exception))

        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT EXTRACT(month FROM date) FROM warehouse.fact_daily_performance"
            )

        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT date + INTERVAL '1 day' FROM warehouse.fact_daily_performance"
            )

        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT marketplace COLLATE \"C\" FROM warehouse.fact_daily_performance"
            )

    # -------------------------------------------------------------------------
    # Rejection: LIMIT Violations
    # -------------------------------------------------------------------------
    def test_reject_limit_zero(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products LIMIT 0")

    def test_reject_negative_limit(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products LIMIT -5")

    def test_reject_float_limit(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products LIMIT 10.5")

    def test_reject_expression_and_subquery_limit(self) -> None:
        with self.assertRaises(SqlGuardError):
            self.guard.validate("SELECT * FROM warehouse.dim_products LIMIT 1 + 1")
        with self.assertRaises(SqlGuardError):
            self.guard.validate(
                "SELECT * FROM warehouse.dim_products LIMIT (SELECT 10 FROM warehouse.dim_products)"
            )

    def test_reject_exceeded_limit(self) -> None:
        with self.assertRaises(SqlGuardError) as ctx:
            self.guard.validate("SELECT * FROM warehouse.dim_products LIMIT 2000")
        self.assertIn("exceeds maximum allowed rows", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
