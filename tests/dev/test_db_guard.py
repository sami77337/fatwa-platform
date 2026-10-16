"""No driver, database, or Django required: isolation guard regression tests."""

import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "tools/dev/db_test_guard.py"
SPEC = importlib.util.spec_from_file_location("a6_db_guard", MODULE)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class Cursor:
    def __init__(self, database_names=None, identity=None, role_flags=None, tables=None):
        self.database_names = database_names or [("postgres",), ("test_fatwa_a6_012345abcdef",)]
        self.identity = identity or ("test_fatwa_a6_012345abcdef", "fatwa_a6_test", 180006)
        self.role_flags = role_flags or (False,) * 5
        self.tables = tables or []
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql):
        self.statements.append(sql)
        assert sql.startswith("SELECT ")

    def fetchone(self):
        return self.identity if "current_database()" in self.statements[-1] else self.role_flags

    def fetchall(self):
        return self.database_names if "FROM pg_database" in self.statements[-1] else self.tables

    def cursor(self):
        return self


class DatabaseGuardTests(unittest.TestCase):
    def environment(self):
        return {
            "PGHOST": "127.0.0.1", "PGPORT": "55440",
            "PGDATABASE": "test_fatwa_a6_012345abcdef", "PGUSER": "fatwa_a6_test",
            "FATWA_A6_TEST_PASSWORD_FILE": "synthetic-test-only-file",
        }

    def test_protected_and_ambiguous_targets_fail_before_any_connection(self):
        for key, values in {
            "PGHOST": ["localhost", "postgres", "external.invalid", ""],
            "PGPORT": ["5432", "55432", "8000", "0", "65536", "invalid"],
            "PGDATABASE": ["fatwa_reference", "test_fatwa_reference_dev", "", "test_fatwa_a6_../live"],
            "PGUSER": ["fatwa_app", "postgres", ""],
            "FATWA_A6_TEST_PASSWORD_FILE": [""],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(guard.IsolationError):
                    guard.candidate_settings({**self.environment(), key: value})

    def test_inherited_connection_overrides_are_refused(self):
        for key in ("PGPASSWORD", "DATABASE_URL", "PGSERVICE", "PGOPTIONS", "PGHOSTADDR", "PGPASSFILE"):
            with self.subTest(key=key), self.assertRaises(guard.IsolationError):
                guard.candidate_settings({**self.environment(), key: "synthetic-secret"})

    def test_candidate_connections_force_read_only(self):
        settings, _ = guard.candidate_settings(self.environment())
        self.assertIn("default_transaction_read_only=on", settings["options"])
        self.assertEqual(settings["dbname"], "test_fatwa_a6_012345abcdef")
        self.assertNotIn("password", settings)

    def test_same_cluster_even_with_distinct_database_is_refused(self):
        cursor = Cursor(database_names=[("fatwa_reference",), ("test_fatwa_a6_012345abcdef",)])
        with self.assertRaises(guard.IsolationError):
            guard.inspect_candidate(cursor, "test_fatwa_a6_012345abcdef")
        self.assertEqual(len(cursor.statements), 2)

    def test_different_identity_privileges_or_existing_tables_are_refused(self):
        for candidate in (
            Cursor(identity=("fatwa_reference", "fatwa_app", 180006)),
            Cursor(role_flags=(True, False, False, False, False)),
            Cursor(tables=[("public", "reference_referenceheading")]),
        ):
            with self.subTest(candidate=candidate), self.assertRaises(guard.IsolationError):
                guard.inspect_candidate(candidate, "test_fatwa_a6_012345abcdef")

    def test_even_valid_preflight_never_runs_django_or_mutations(self):
        candidate = Cursor()
        result = guard.inspect_candidate(candidate, "test_fatwa_a6_012345abcdef")
        self.assertEqual(result["preflight"], "PASS")
        self.assertEqual(result["django_postgresql_tests"], "NOT_RUN")
        self.assertEqual(len(candidate.statements), 4)
        self.assertTrue(all(sql.startswith("SELECT ") for sql in candidate.statements))


if __name__ == "__main__":
    unittest.main()
