"""Failure evidence from the CLI; no simulated engine is called real acceptance."""

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from . import acceptance


class ClamAVAcceptanceAvailabilityTests(TestCase):
    def test_missing_actual_engine_writes_unavailable_artifact_and_nonzero_exit(self):
        with TemporaryDirectory(prefix="fatwa-clamav-unavailable-") as temporary:
            root = Path(temporary)
            output = root / "evidence" / "acceptance.json"
            with redirect_stdout(StringIO()):
                status = acceptance.main(
                    [
                        "--executable",
                        str(root / "missing-clamscan"),
                        "--database-directory",
                        str(root / "missing-cvd-snapshot"),
                        "--signature-source",
                        "https://database.clamav.net",
                        "--max-daily-age-days",
                        "2",
                        "--memory-bytes",
                        str(2 * 1024 * 1024 * 1024),
                        "--timeout-seconds",
                        "30",
                        "--output",
                        str(output),
                    ]
                )
            result = json.loads(output.read_text())
            self.assertEqual(status, 2)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertEqual(result["failure_stage"], "engine_or_database_path")
            self.assertFalse(result["real_engine_verified"])
            self.assertFalse(result["production_changed"])
            self.assertFalse(result["domain_rows_written"])
            self.assertEqual(result["samples"], [])
            self.assertEqual(result["reports"], [])

    def test_unbounded_timeout_cannot_produce_real_engine_evidence(self):
        result = acceptance.evaluate(
            executable="/nonexistent-clamscan",
            database_directory="/nonexistent-cvd-snapshot",
            max_daily_age_days=2,
            memory_bytes=2 * 1024 * 1024 * 1024,
            timeout_seconds=float("inf"),
            signature_source="https://database.clamav.net",
        )
        self.assertEqual(len(acceptance.EICAR), 68)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["failure_stage"], "configuration")
        self.assertFalse(result["real_engine_verified"])
