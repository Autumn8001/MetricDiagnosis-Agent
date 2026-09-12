#!/usr/bin/env python3
"""Independent verification script for PostgreSQL metricsleuth_readonly role.

Verifies:
1. Connection identity and database-scoped session defaults (read-only, timeout, search_path).
2. Cluster-level role attributes and absence of inherited role memberships.
3. Precise table grants set matching exactly {dim_products: SELECT, fact_daily_performance: SELECT}.
4. Schema privileges (USAGE = true, CREATE = false) and table non-SELECT privileges (all false).
5. Non-ownership of database, schemas, and warehouse tables.
6. Allowed read operations on designated warehouse tables.
7. Default transaction read-only protection (SQLSTATE 25006).
8. Underlying object privileges boundary when read-only is disabled (SQLSTATE 42501).
9. Rejection of other write, DDL, and table management operations.
10. Statement timeout enforcement on slow queries (SQLSTATE 57014).
11. Data integrity preservation across entire test cycle.
"""

import os
import sys
import time

import psycopg


def get_db_url() -> str:
    """Retrieve and validate the READONLY_DATABASE_URL environment variable."""
    url = os.environ.get("READONLY_DATABASE_URL", "").strip()
    if not url:
        print("ERROR: READONLY_DATABASE_URL environment variable must be set and non-empty.", file=sys.stderr)
        sys.exit(1)
    return url


def verify_identity_and_defaults(url: str) -> None:
    """Verify session user, role attributes, and session defaults."""
    print("1. Verifying role identity, attributes, and session defaults...")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Check session/current user
            cur.execute("SELECT current_user, session_user, current_setting('search_path');")
            curr_user, sess_user, search_path = cur.fetchone()
            assert curr_user == "metricsleuth_readonly", f"Expected current_user 'metricsleuth_readonly', got '{curr_user}'"
            assert sess_user == "metricsleuth_readonly", f"Expected session_user 'metricsleuth_readonly', got '{sess_user}'"
            assert search_path.strip() == "pg_catalog", f"Expected search_path 'pg_catalog', got '{search_path}'"

            # Check transaction_read_only
            cur.execute("SHOW default_transaction_read_only;")
            (def_ro,) = cur.fetchone()
            assert def_ro.lower() == "on", f"Expected default_transaction_read_only 'on', got '{def_ro}'"

            cur.execute("SHOW transaction_read_only;")
            (trans_ro,) = cur.fetchone()
            assert trans_ro.lower() == "on", f"Expected transaction_read_only 'on', got '{trans_ro}'"

            # Check statement_timeout (1s / 1000ms equivalent)
            cur.execute("SHOW statement_timeout;")
            (timeout_setting,) = cur.fetchone()
            assert timeout_setting.lower() in ("1s", "1000ms", "1000"), f"Expected statement_timeout '1s' or '1000ms', got '{timeout_setting}'"

            # Check pg_roles catalog attributes
            cur.execute(
                """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication,
                       rolbypassrls, rolinherit, rolcanlogin, rolconnlimit
                FROM pg_roles
                WHERE rolname = 'metricsleuth_readonly';
                """
            )
            row = cur.fetchone()
            assert row is not None, "Role 'metricsleuth_readonly' not found in pg_roles"
            (
                rolsuper,
                rolcreatedb,
                rolcreaterole,
                rolreplication,
                rolbypassrls,
                rolinherit,
                rolcanlogin,
                rolconnlimit,
            ) = row

            assert not rolsuper, "Role must not be SUPERUSER"
            assert not rolcreatedb, "Role must not have CREATEDB"
            assert not rolcreaterole, "Role must not have CREATEROLE"
            assert not rolreplication, "Role must not have REPLICATION"
            assert not rolbypassrls, "Role must not have BYPASSRLS"
            assert not rolinherit, "Role must not have INHERIT"
            assert rolcanlogin, "Role must have LOGIN"
            assert rolconnlimit == 5, f"Expected connection limit 5, got {rolconnlimit}"

            # Check absence of role memberships
            cur.execute(
                """
                SELECT COUNT(*)
                FROM pg_auth_members
                WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'metricsleuth_readonly');
                """
            )
            (membership_count,) = cur.fetchone()
            assert membership_count == 0, f"Role must not have role memberships, found {membership_count}"

    print("   -> Role identity, attributes, and session defaults: PASS")


def verify_precise_privileges_and_ownership(url: str) -> None:
    """Verify that table grants match exact allowlist, schema permissions are minimal, and role owns no objects."""
    print("2. Verifying precise privilege grants and non-ownership...")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # 2.1 Exact table grants assertion via information_schema.role_table_grants
            cur.execute(
                """
                SELECT table_schema, table_name, privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'metricsleuth_readonly'
                ORDER BY table_schema, table_name, privilege_type;
                """
            )
            grants = set(cur.fetchall())
            expected_grants = {
                ("warehouse", "dim_products", "SELECT"),
                ("warehouse", "fact_daily_performance", "SELECT"),
            }
            assert grants == expected_grants, f"Privilege grants mismatch. Expected {expected_grants}, got {grants}"

            # 2.2 Schema privileges assertion
            cur.execute(
                """
                SELECT
                    has_schema_privilege('metricsleuth_readonly', 'warehouse', 'USAGE'),
                    has_schema_privilege('metricsleuth_readonly', 'warehouse', 'CREATE');
                """
            )
            has_usage, has_create = cur.fetchone()
            assert has_usage is True, "Role must have USAGE on schema warehouse"
            assert has_create is False, "Role must NOT have CREATE on schema warehouse"

            # 2.3 Non-SELECT table privileges assertion
            cur.execute(
                """
                SELECT
                    has_table_privilege('metricsleuth_readonly', 'warehouse.dim_products', 'INSERT'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.dim_products', 'UPDATE'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.dim_products', 'DELETE'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.dim_products', 'TRUNCATE'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.dim_products', 'REFERENCES'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.dim_products', 'TRIGGER'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.fact_daily_performance', 'INSERT'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.fact_daily_performance', 'UPDATE'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.fact_daily_performance', 'DELETE'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.fact_daily_performance', 'TRUNCATE'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.fact_daily_performance', 'REFERENCES'),
                    has_table_privilege('metricsleuth_readonly', 'warehouse.fact_daily_performance', 'TRIGGER');
                """
            )
            non_select_privileges = cur.fetchone()
            assert not any(non_select_privileges), f"Role must have zero non-SELECT table privileges, got {non_select_privileges}"

            # 2.4 Non-ownership assertion
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM pg_database WHERE datname = 'metricsleuth' AND datdba = (SELECT oid FROM pg_roles WHERE rolname = 'metricsleuth_readonly')),
                    (SELECT COUNT(*) FROM pg_namespace WHERE nspname = 'warehouse' AND nspowner = (SELECT oid FROM pg_roles WHERE rolname = 'metricsleuth_readonly')),
                    (SELECT COUNT(*) FROM pg_class WHERE relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'warehouse') AND relowner = (SELECT oid FROM pg_roles WHERE rolname = 'metricsleuth_readonly'));
                """
            )
            db_owner_cnt, nsp_owner_cnt, tbl_owner_cnt = cur.fetchone()
            assert db_owner_cnt == 0, "Role must not own the metricsleuth database"
            assert nsp_owner_cnt == 0, "Role must not own the warehouse schema"
            assert tbl_owner_cnt == 0, "Role must not own any warehouse tables"

    print("   -> Precise privilege grants and non-ownership: PASS")


def verify_allowed_reads(url: str) -> tuple[int, int]:
    """Verify SELECT operations succeed on allowed warehouse tables."""
    print("3. Verifying allowed read access on warehouse tables...")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM warehouse.dim_products;")
            (products_count,) = cur.fetchone()
            assert products_count > 0, f"Expected positive row count in dim_products, got {products_count}"

            cur.execute("SELECT COUNT(*) FROM warehouse.fact_daily_performance;")
            (perf_count,) = cur.fetchone()
            assert perf_count > 0, f"Expected positive row count in fact_daily_performance, got {perf_count}"

    print(f"   -> Read allowed tables (dim_products={products_count}, fact_daily_performance={perf_count}): PASS")
    return products_count, perf_count


def verify_default_readonly_transaction(url: str) -> None:
    """Verify default transaction is read-only (SQLSTATE 25006)."""
    print("4. Verifying default read-only transaction rejection (SQLSTATE 25006)...")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("UPDATE warehouse.fact_daily_performance SET sessions = sessions WHERE FALSE;")
                conn.rollback()
                raise AssertionError("Expected UPDATE in default read-only transaction to fail, but it succeeded.")
            except psycopg.errors.ReadOnlySqlTransaction as e:
                assert e.sqlstate == "25006", f"Expected SQLSTATE 25006, got {e.sqlstate}"
                conn.rollback()
            except Exception as e:
                conn.rollback()
                raise AssertionError(f"Expected ReadOnlySqlTransaction (25006), got {type(e).__name__}: {e}") from e

    print("   -> Default read-only transaction rejection (SQLSTATE 25006): PASS")


def verify_object_privileges_boundary(url: str) -> None:
    """Verify that even when transaction_read_only is turned off, lack of object privilege rejects writes (SQLSTATE 42501)."""
    print("5. Verifying object privilege boundary when read-only is disabled (SQLSTATE 42501)...")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # Explicitly turn off read-only mode in session
            cur.execute("SET default_transaction_read_only = off;")
            cur.execute("SET transaction_read_only = off;")

            try:
                cur.execute("UPDATE warehouse.fact_daily_performance SET sessions = sessions WHERE FALSE;")
                conn.rollback()
                raise AssertionError("Expected UPDATE without object write privilege to fail, but it succeeded.")
            except psycopg.errors.InsufficientPrivilege as e:
                assert e.sqlstate == "42501", f"Expected SQLSTATE 42501, got {e.sqlstate}"
                conn.rollback()
            except Exception as e:
                conn.rollback()
                raise AssertionError(f"Expected InsufficientPrivilege (42501), got {type(e).__name__}: {e}") from e

    print("   -> Object privilege boundary (SQLSTATE 42501): PASS")


def verify_other_operations_rejected(url: str) -> None:
    """Verify various write, DDL, and table management operations are rejected."""
    print("6. Verifying rejection of other write, DDL, and schema operations...")

    forbidden_statements = [
        (
            "INSERT",
            "INSERT INTO warehouse.dim_products (asin, product_name, category) VALUES ('PROBE-X', 'Test', 'Cat');",
        ),
        (
            "DELETE",
            "DELETE FROM warehouse.fact_daily_performance WHERE FALSE;",
        ),
        (
            "TRUNCATE",
            "TRUNCATE TABLE warehouse.dim_products;",
        ),
        (
            "ALTER TABLE",
            "ALTER TABLE warehouse.dim_products ADD COLUMN probe_col INT;",
        ),
        (
            "DROP TABLE",
            "DROP TABLE warehouse.dim_products;",
        ),
        (
            "CREATE TABLE",
            "CREATE TABLE warehouse.probe_table (id INT);",
        ),
    ]

    for label, sql in forbidden_statements:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                # Disable read-only setting to test underlying object privileges
                cur.execute("SET default_transaction_read_only = off;")
                cur.execute("SET transaction_read_only = off;")
                try:
                    cur.execute(sql)
                    conn.rollback()
                    raise AssertionError(f"Forbidden operation '{label}' unexpectedly succeeded: {sql}")
                except (psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction) as e:
                    assert e.sqlstate in ("42501", "25006"), f"Expected 42501 or 25006 for '{label}', got {e.sqlstate}"
                    conn.rollback()
                except Exception as e:
                    conn.rollback()
                    raise AssertionError(f"Unexpected error type for '{label}': {type(e).__name__} ({e})") from e

    print("   -> Other write/DDL operations rejection: PASS")


def verify_statement_timeout(url: str) -> None:
    """Verify statement_timeout cancels long queries with SQLSTATE 57014."""
    print("7. Verifying statement_timeout cancellation (SQLSTATE 57014)...")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            start_time = time.time()
            try:
                cur.execute("SELECT pg_sleep(2);")
                raise AssertionError("Expected pg_sleep(2) to be canceled by statement_timeout, but it completed.")
            except psycopg.errors.QueryCanceled as e:
                elapsed = time.time() - start_time
                assert e.sqlstate == "57014", f"Expected SQLSTATE 57014 (query_canceled), got {e.sqlstate}"
                assert 0.5 <= elapsed < 2.0, f"Expected elapsed time between 0.5s and 2.0s, got {elapsed:.2f}s"
                print(f"   -> Statement timeout canceled after {elapsed:.2f}s with SQLSTATE 57014: PASS")
            except Exception as e:
                raise AssertionError(f"Expected QueryCanceled (57014), got {type(e).__name__}: {e}") from e


def main() -> None:
    """Run all readonly role verifications."""
    url = get_db_url()
    print("================================================================================")
    print("MetricSleuth: PostgreSQL Readonly Role Verification Suite")
    print("================================================================================")

    # 1. Identity, attributes, and session defaults
    verify_identity_and_defaults(url)

    # 2. Precise privileges and non-ownership assertions
    verify_precise_privileges_and_ownership(url)

    # 3. Allowed reads and baseline counts
    initial_products, initial_perf = verify_allowed_reads(url)

    # 4. Default read-only transaction (SQLSTATE 25006)
    verify_default_readonly_transaction(url)

    # 5. Object privilege boundary (SQLSTATE 42501)
    verify_object_privileges_boundary(url)

    # 6. Other write/DDL statements rejection
    verify_other_operations_rejected(url)

    # 7. Timeout enforcement (SQLSTATE 57014)
    verify_statement_timeout(url)

    # 8. Confirm data integrity (row counts unchanged)
    final_products, final_perf = verify_allowed_reads(url)
    assert initial_products == final_products, f"dim_products count changed: {initial_products} -> {final_products}"
    assert initial_perf == final_perf, f"fact_daily_performance count changed: {initial_perf} -> {final_perf}"

    print("================================================================================")
    print("ALL POSTGRESQL READONLY ROLE VERIFICATIONS PASSED SUCCESSFULLY")
    print("================================================================================")


if __name__ == "__main__":
    main()
