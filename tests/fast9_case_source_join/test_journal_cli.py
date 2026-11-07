"""Exercise the fixed-event operator commands with a fresh interpreter per delivery."""

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from apps.fast9_case_source_join.source_history import source_receipt
from apps.fast9_case_source_join.source_journal import JOURNAL_FILENAME


class JournalCommandTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def command(self, *args, success=True):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "tools.fast9_case_source_join.journal",
                "--synthetic-fixtures-only",
                "--case-key",
                "intake-7",
                *args,
            ],
            env={**os.environ, "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(self.directory)},
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if not success:
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(result.stdout)
            return None
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_commands_reopen_complete_history_without_synthesizing_a_predecessor(self):
        self.assertEqual(self.command("show")["status"], "NO_SAVED_HISTORY")
        self.assertFalse(list(self.directory.iterdir()))
        self.command("record", "corrected", success=False)
        self.assertEqual(self.command("show")["events"], [])
        first = self.command("record", "received")
        second = self.command("record", "corrected")
        self.assertEqual(self.command("record", "corrected"), second)
        last = self.command("record", "restored")
        self.assertEqual(self.command("show"), last)
        events = last["events"]
        self.assertEqual(
            [e["id"] for e in events], ["received-intake-7", "edit-example", "restore-example"]
        )
        self.assertEqual(events[:2], second["events"])
        self.assertEqual(events[:1], first["events"])
        original = sha256(source_receipt("intake-7").body_utf8).hexdigest()
        self.assertEqual(events[0]["question_sha256"], original)
        self.assertEqual(events[-1]["question_sha256"], original)
        self.assertNotEqual(events[1]["question_sha256"], original)

    def test_deletion_keeps_the_original_through_another_process(self):
        self.command("record", "received")
        edited = self.command("record", "corrected")
        deleted = self.command("record", "deleted")
        self.assertEqual(self.command("show"), deleted)

        self.assertEqual(deleted["events"][:-1], edited["events"])
        self.assertIsNone(deleted["events"][-1]["question_sha256"])
        self.command("record", "restored", success=False)
        self.assertEqual(self.command("show"), deleted)

    def test_separately_retained_checkpoint_rejects_rolled_back_and_divergent_snapshots(self):
        path = self.directory / JOURNAL_FILENAME
        initial = self.command("record", "received")["checkpoint"]
        self.command("record", "corrected")
        before_fork = path.read_bytes()
        restored = self.command("record", "restored")["checkpoint"]
        verified = self.command("verify", str(initial["count"]), initial["sha256"])
        self.assertEqual(verified["verified_prefix"], initial)
        self.assertEqual(verified["checkpoint"], restored)
        path.write_bytes(before_fork)
        self.assertEqual(self.command("show")["checkpoint"]["count"], 2)
        self.command("verify", str(restored["count"]), restored["sha256"], success=False)
        other = self.command("record", "deleted")["checkpoint"]
        self.assertEqual(other["count"], restored["count"])
        self.assertNotEqual(other["sha256"], restored["sha256"])
        self.command("verify", str(restored["count"]), restored["sha256"], success=False)
        self.assertEqual(
            self.command("verify", str(other["count"]), other["sha256"])["verified_prefix"], other
        )
