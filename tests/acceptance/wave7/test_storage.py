"""Cross-process foundation evidence; full E1/E2/E3 workflow remains separate."""
import json
from pathlib import Path
import subprocess
import sys

from django.conf import settings
from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference
from .target import require_lane_configuration

require_lane_configuration()


class StorageProcessTests(TransactionTestCase):
    def setUp(self):
        context = g.require_synthetic_write(synthetic_fixtures_only=True)
        self.assertEqual(context.database_name, settings.WAVE7_TEST_DATABASE_NAME)
        # Shared fixture seed outside any outer transaction; it owns its unit.
        f.seed_reference_catalog(synthetic_fixtures_only=True)

    def child(self, action, key="E6-FOUNDATION-PROBE"):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("process_probe.py")),
                                 action, "--key", key], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        # This is a probe report with source text strings, not a source JSON decoder.
        return json.loads(result.stdout)

    def test_write_and_two_new_process_reads_preserve_exact_originals(self):
        created = self.child("create")
        self.assertEqual(created, self.child("inspect"))
        self.assertEqual(created, self.child("inspect"))
        self.assertEqual(created["raw_text"].encode("utf-8"), f.synthetic_payload())
        self.assertEqual(created["raw_sha256"], created["payload_sha256"])
        self.assertEqual(created["payload_snapshot"], created["raw_text"])
        self.assertEqual(len(created["items"]), 8)
        self.assertEqual(created["items"][0]["question_original"], f.ORIGINAL_QUESTION)
        self.assertEqual(created["items"][-1]["original_row"], "null")
        self.assertTrue(all(row["intake_status"] == "RECEIVED" for row in created["items"]))
        self.assertEqual(created["event_count"], 0)
        self.assertTrue(all(ref["reference_status"] == "UNVERIFIED" and not ref["citation_text"]
                            for ref in created["references"]))
        raw = created["raw_text"].encode("utf-8")
        for row in [*created["items"], *created["references"]]:
            text = row.get("original_row", row.get("original_pointer"))
            self.assertEqual(raw[row["source_byte_start"]:row["source_byte_end"]], text.encode("utf-8"))

    def test_lossless_numeric_invalid_row_and_reference_survive_new_process(self):
        raw = (b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":'
               b'[{"external_id":73.000000000000001,"question":null,"reference_links":[1e-20000,null]}]}')
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = IntakeBatch.objects.create(idempotency_key="E6-NUMERIC", original_payload=raw,
                                              payload_sha256=parsed.payload_sha256)
            source = parsed.item_sources[0]
            item = IntakeItem.objects.create(batch=batch, row_ordinal=1, external_id=None,
                original_row=source.text, source_byte_start=source.start, source_byte_end=source.end,
                intake_status="BLOCKED_INVALID")
            for ordinal, pointer in enumerate(parsed.reference_sources[0], 1):
                IntakeReference.objects.create(intake_item=item, reference_ordinal=ordinal,
                    original_pointer=pointer.text, source_byte_start=pointer.start, source_byte_end=pointer.end)
        result = self.child("inspect", "E6-NUMERIC")
        self.assertEqual(result["raw_text"].encode("utf-8"), raw)
        self.assertEqual([row["original_pointer"] for row in result["references"]], ["1e-20000", "null"])
        self.assertIsNone(result["items"][0]["external_id"])
        self.assertEqual(result["items"][0]["intake_status"], "BLOCKED_INVALID")

    def test_guard_rejects_application_outer_atomic(self):
        with transaction.atomic(), self.assertRaises(g.SyntheticWriteDenied) as caught:
            g.require_synthetic_write(synthetic_fixtures_only=True)
        self.assertEqual(caught.exception.code, "GUARD_BEFORE_TRANSACTION_REQUIRED")
        self.assertEqual(IntakeBatch.objects.count(), 0)

    def test_process_write_retains_marker_and_actual_test_database_identity(self):
        before = g.require_owned_database(synthetic_fixtures_only=True)
        self.child("create")
        after = g.require_owned_database(synthetic_fixtures_only=True)
        self.assertEqual(before, after)
        self.assertEqual(IntakeBatch.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int")
            name, role, version = cursor.fetchone()
        self.assertEqual(name, settings.WAVE7_TEST_DATABASE_NAME)
        self.assertEqual(role, c.DATABASE_ROLE)
        self.assertIn(version // 10000, [17, 18])
