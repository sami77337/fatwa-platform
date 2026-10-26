"""Verify acceptance discovery refuses the wrong DB without connecting anywhere."""

import os
import subprocess
import sys
from unittest import TestCase


class PreflightTests(TestCase):
    def discover(self, target):
        script = """
import django
django.setup()
from django.db import connection
from unittest.mock import patch
from django.test.runner import DiscoverRunner
with patch.object(connection, 'ensure_connection', side_effect=AssertionError('DB_CONNECT')):
    try:
        suite = DiscoverRunner().build_suite(['tests.fast8_fiqh_navigation.postgresql'])
    except RuntimeError as error:
        print(str(error))
    else:
        print('discovered=' + str(suite.countTestCases()))
"""
        return subprocess.run(
            [sys.executable, "-B", "-c", script],
            env={
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings.test",
                "PGTESTDATABASE": target,
                "FATWA_PRODUCTION": "0",
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def test_wrong_target_refused_before_any_database_connection(self):
        result = self.discover("test_wrong_synthetic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "Dedicated synthetic PostgreSQL test database required"
        )

    def test_exact_target_discovers_three_cases_without_connecting(self):
        result = self.discover("test_fast8_fiqh_navigation_synthetic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("discovered=3", result.stdout)
