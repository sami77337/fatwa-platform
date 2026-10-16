"""Explicit opt-in QA of an existing reviewed DB; never creates a test database."""

import io
import json
import os
import unittest
from pathlib import Path

import django
from django.core.management import call_command

from tools.fiqh_import.book622 import ARCHIVE_SHA256, INPUT_MEMBER, MAPPED_CHECKSUM
from tools.fiqh_import.owner_r1 import INPUT_PINS

ARCHIVE = Path(os.environ.get(
    "FATWA_622_ARCHIVE", "_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip"
))
EDITION = os.environ.get("FATWA_622_AUDIT_EDITION", "")


def setUpModule():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    django.setup()


@unittest.skipUnless(
    ARCHIVE.is_file() and EDITION,
    "REAL_DB_AUDIT_NOT_RUN: requires trusted ZIP and explicit FATWA_622_AUDIT_EDITION",
)
class ExistingSnapshotReadOnlyTests(unittest.TestCase):
    def test_every_historical_field_matches_and_read_only_rerun_is_identical(self):
        self.assertTrue(EDITION.isascii() and EDITION.isdecimal() and 0 < int(EDITION) < 2**63)
        reports = []
        for _ in range(2):
            output = io.StringIO()
            call_command(
                "audit_book622", archive=str(ARCHIVE), edition=int(EDITION),
                heading_id=1, max_issues=20, stdout=output,
            )
            reports.append(json.loads(output.getvalue()))
        self.assertEqual(reports[0], reports[1])
        report = reports[0]
        self.assertTrue(report["valid"])
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["matched_rows"], 11397)
        self.assertEqual(report["issue_count"], 0)
        self.assertEqual((report["actual_roots"], report["actual_max_depth"]), (32, 5))
        self.assertEqual(report["mapped_checksum"], MAPPED_CHECKSUM)
        self.assertEqual(report["source_archive_sha256"], ARCHIVE_SHA256)
        self.assertEqual(report["source_input_sha256"], INPUT_PINS["jsonl"])
        self.assertEqual(report["database_import"], "NOT_RUN")
        self.assertLessEqual(len(report["citation"]["path"]), 5)
        self.assertEqual(report["citation"]["source_id"], "622-1")
        print(json.dumps({
            "fixture": INPUT_MEMBER, "archive_sha256": ARCHIVE_SHA256,
            "input_sha256": INPUT_PINS["jsonl"], "mapped_checksum": MAPPED_CHECKSUM,
            "matched_rows": 11397, "database_import": "NOT_RUN",
            "transaction": report["transaction"], "postgres_version": report["postgres_version"],
        }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
