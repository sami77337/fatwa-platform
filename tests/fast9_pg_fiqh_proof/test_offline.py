"""No database connection is permitted by these tests."""

import os
import subprocess
import sys
from unittest import TestCase


class GuardTests(TestCase):
    def probe(self, body, **overrides):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "FATWA_PRODUCTION": "0",
            "FAST9_PG_FIQH_SYNTHETIC_ONLY": "1",
            "PGDATABASE": "b6_ephemeral",
            "PGUSER": "fatwa_ci",
            "PGHOST": "127.0.0.1",
            "PGPORT": "5432",
            "PGTESTDATABASE": "test_fast8_fiqh_navigation_synthetic",
            "EXPECTED_PG_MAJOR": "17",
            **overrides,
        }
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                """
import django
django.setup()
from django.db import connection
from unittest.mock import patch
with patch.object(connection, 'ensure_connection', side_effect=AssertionError('DB_CONNECT')):
"""
                + "\n".join("    " + line for line in body.splitlines()),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertNotIn("DB_CONNECT", result.stderr)
        return result

    def test_missing_opt_in_refuses_before_connection(self):
        result = self.probe(
            "from tools.fast9_pg_fiqh_proof.runner import SyntheticRunner\nSyntheticRunner()",
            FAST9_PG_FIQH_SYNTHETIC_ONLY="",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SyntheticGuardError", result.stderr)

    def test_wrong_configuration_refuses_before_connection(self):
        for key, value in {
            "PGDATABASE": "fatwa_reference_dev",
            "PGTESTDATABASE": "test_other",
            "PGUSER": "real_user",
            "PGHOST": "remote.example",
            "PGPORT": "9999",
            "EXPECTED_PG_MAJOR": "16",
        }.items():
            with self.subTest(key=key):
                result = self.probe(
                    "from tools.fast9_pg_fiqh_proof.runner import SyntheticRunner\nSyntheticRunner()",
                    **{key: value},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SyntheticGuardError", result.stderr)

    def test_direct_discovery_is_rejected_before_setup_databases(self):
        result = self.probe(
            "from django.test.runner import DiscoverRunner\n"
            "DiscoverRunner().build_suite(['tests.fast9_pg_fiqh_proof.postgresql'])"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SyntheticGuardError", result.stderr)

    def test_trusted_runner_discovers_exact_suite_without_connecting(self):
        result = self.probe(
            "from tools.fast9_pg_fiqh_proof.runner import SyntheticRunner, LABEL\n"
            "suite = SyntheticRunner().build_suite([LABEL])\n"
            "print('discovered=' + str(suite.countTestCases()))"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("discovered=8", result.stdout)

    def test_keepdb_parallel_and_other_labels_are_refused(self):
        for expression in (
            "SyntheticRunner(keepdb=True)",
            "SyntheticRunner(parallel=2)",
            "SyntheticRunner().build_suite(['tests.reference'])",
        ):
            with self.subTest(expression=expression):
                result = self.probe(
                    "from tools.fast9_pg_fiqh_proof.runner import SyntheticRunner\n" + expression
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SyntheticGuardError", result.stderr)

    def test_wrong_live_identity_and_occupied_database_fail_without_writes(self):
        result = self.probe("""
from unittest.mock import Mock
from tools.fast9_pg_fiqh_proof.runner import verify_identity, require_unused, SyntheticGuardError
for row in [('user_database', 'fatwa_ci', '170000'),
            ('b6_ephemeral', 'wrong_role', '170000'),
            ('b6_ephemeral', 'fatwa_ci', '180000')]:
    cursor = Mock()
    cursor.fetchone.return_value = row
    try:
        verify_identity(cursor, 'b6_ephemeral')
    except SyntheticGuardError:
        pass
    else:
        raise AssertionError('identity accepted')
    assert all(call.args[0].startswith('SELECT') for call in cursor.execute.call_args_list)
cursor = Mock()
cursor.fetchone.return_value = (1,)
try:
    require_unused(cursor)
except SyntheticGuardError:
    pass
else:
    raise AssertionError('occupied database accepted')
assert cursor.execute.call_count == 1
assert cursor.execute.call_args.args[0].startswith('SELECT')
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_create_race_has_no_drop_or_retry(self):
        result = self.probe("""
from contextlib import nullcontext
from unittest.mock import Mock, patch
from tools.fast9_pg_fiqh_proof.runner import create_without_reuse
cursor = Mock()
cursor.fetchone.side_effect = [('postgres', 'fatwa_ci', '170000'), None]
def execute(sql, *args):
    if sql.startswith('CREATE'):
        raise RuntimeError('synthetic duplicate-name race')
cursor.execute.side_effect = execute
with patch.object(connection.creation, '_nodb_cursor', return_value=nullcontext(cursor)):
    try:
        create_without_reuse(0, True)
    except RuntimeError as error:
        assert str(error) == 'synthetic duplicate-name race'
    else:
        raise AssertionError('create failure accepted')
sql = [call.args[0] for call in cursor.execute.call_args_list]
assert len(sql) == 3, sql
assert sql[-1] == 'CREATE DATABASE "test_fast8_fiqh_navigation_synthetic"'
assert not any('DROP' in query for query in sql)
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_occupied_target_blocks_django_setup_and_migrations(self):
        result = self.probe("""
from contextlib import nullcontext
from unittest.mock import Mock, patch
from django.test.runner import DiscoverRunner
from tools.fast9_pg_fiqh_proof.runner import SyntheticRunner, SyntheticGuardError
cursor = Mock()
cursor.fetchone.side_effect = [('b6_ephemeral', 'fatwa_ci', '170000'), (1,)]
with patch.object(connection, 'cursor', return_value=nullcontext(cursor)), \
     patch.object(DiscoverRunner, 'setup_databases') as setup, \
     patch('tools.fast9_pg_fiqh_proof.runner.revision_evidence'):
    try:
        SyntheticRunner().setup_databases()
    except SyntheticGuardError:
        pass
    else:
        raise AssertionError('occupied database accepted')
    setup.assert_not_called()
assert all(call.args[0].startswith('SELECT') for call in cursor.execute.call_args_list)
""")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixture_write_guard_rejects_untrusted_runtime(self):
        result = self.probe(
            "from tools.fast9_pg_fiqh_proof.runner import require_running_database\n"
            "require_running_database()"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SyntheticGuardError", result.stderr)


class FixtureTests(TestCase):
    def test_exact_fixture_and_literal_checksum(self):
        from tools.fast9_pg_fiqh_proof.proof import CHECKSUM, checked_fixture

        prepared, _ = checked_fixture()
        self.assertEqual(prepared.checksum, CHECKSUM)
        self.assertEqual(len(prepared.records), 9)
        self.assertEqual(prepared.records[2].title_original, "  فَصْلٌ <اصطناعي> e\u0301  ")

    def test_fixture_drift_is_not_accepted(self):
        from unittest.mock import patch

        from tools.fast9_pg_fiqh_proof import proof

        with patch.object(proof, "FIXTURE_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "fixture"):
                proof.checked_fixture()
