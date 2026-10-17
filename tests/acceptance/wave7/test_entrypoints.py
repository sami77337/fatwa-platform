"""Explicit pure E1 integration regression for the recovered CLI contract.

Run separately once actual E1 command files exist. Missing command/flag fails;
this module is not added to the currently green baseline/pure suite by fallback.
"""
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.wave7_test")
import django
django.setup()

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase
from apps.intake_workflow import contracts as c, fixtures as f


class IntakeCLIContractTests(SimpleTestCase):
    def test_check_accepts_approved_named_input_without_database_access(self):
        raw = f.synthetic_payload()
        with TemporaryDirectory(prefix="e6-wave7-cli-") as folder:
            source = Path(folder, "known-synthetic.json")
            source.write_bytes(raw)
            output = io.StringIO()
            try:
                call_command("wave7_intake", "check", "--input", str(source),
                             "--synthetic-fixtures-only", stdout=output)
            except CommandError as error:
                self.fail("Approved named --input CLI contract rejected: " + str(error))
        report = json.loads(output.getvalue())  # CLI metadata, not source JSON
        self.assertEqual(report["status"], "CHECKED")
        self.assertEqual(report["payload_sha256"], c.parse_synthetic_payload(
            raw, synthetic_fixtures_only=True).payload_sha256)
        self.assertEqual(report["item_count"], 8)
