"""Run the opt-in command negatively without opening any database connection."""

import json
import os
import subprocess
import sys
import unittest


class PostgreSQLGuardTests(unittest.TestCase):
    def run_guard(self, *args, extra=None):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PG", "FATWA_", "DJANGO_", "DATABASE_URL"))
        }
        env.update(extra or {})
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast9_case_policy_join.postgres_check", *args],
            capture_output=True,
            env=env,
            timeout=15,
        )

    def test_no_explicit_opt_in_reports_not_run(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 3, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)["postgres"], "NOT_RUN")

    def test_opt_in_with_wrong_identity_refuses_before_django_or_connection(self):
        result = self.run_guard(
            "--preauthorized-disposable-only",
            extra={
                "FATWA_PRODUCTION": "0",
                "PGDATABASE": "live",
                "PGUSER": "real-user",
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
            },
        )
        self.assertEqual(result.returncode, 3, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)["reason"], "EXACT_CONFIGURATION_REQUIRED")
        self.assertNotIn(b"real-user", result.stdout + result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)
