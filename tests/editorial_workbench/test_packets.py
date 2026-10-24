"""Packet contracts over real synthetic services; database access is forbidden."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_workbench import services


class CasePacketTests(SimpleTestCase):
    def packet(self, key="history", **selection):
        from apps.editorial_workbench.packets import build_packet

        prepared = services.build_prepared_workbench()
        case = next(c for c in (*services.build_cases(), *prepared.cases) if c.key == key)
        batch = next(
            (b for b in prepared.batches if b.batch_id == getattr(case, "batch_id", None)), None
        )
        return case, build_packet(case, batch, **selection)

    def test_original_intake_identity_and_canonical_unicode_export(self):
        case, packet = self.packet("batch-synthetic-csv-1")
        payload = json.loads(packet.json_bytes)
        self.assertEqual(payload["identity"]["case_key"], case.key)
        self.assertEqual(payload["identity"]["row_ordinal"], 1)
        self.assertEqual(payload["intake"]["question"], "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  ")
        self.assertEqual(
            payload["intake"]["prepared"], json.loads(json.dumps(asdict(case.record.intake)))
        )
        self.assertEqual(payload["intake"]["original_fields"], case.original)
        source = payload["source"]
        self.assertEqual(source["kind"], "parsed_row_serialization")
        self.assertIsNone(source["start"])
        self.assertEqual(sha256(source["input_text"].encode()).hexdigest(), case.payload_sha256)
        self.assertEqual(sha256(source["text"].encode()).hexdigest(), source["text_sha256"])
        self.assertEqual(packet.sha256, sha256(packet.json_bytes).hexdigest())
        self.assertEqual(packet.json_bytes, self.packet(case.key)[1].json_bytes)
        self.assertIn("سُؤَالٌ".encode(), packet.json_bytes)
        self.assertNotIn(b"\\u0633", packet.json_bytes)

    def test_wave7_slice_and_history_serialization_are_distinct_sources(self):
        case, packet = self.packet("intake-1")
        source = json.loads(packet.json_bytes)["source"]
        self.assertEqual(source["kind"], "original_utf8_slice")
        self.assertEqual(
            source["input_text"].encode()[source["start"] : source["end"]].decode(),
            case.raw_source,
        )
        source = json.loads(self.packet()[1].json_bytes)["source"]
        self.assertEqual(source["kind"], "serialized_intake")
        self.assertIsNone(source["start"])

    def test_immutable_snapshots_and_reverse_changes_are_not_persisted_events(self):
        case, packet = self.packet(revision="7", before="11", after="4")
        payload = json.loads(packet.json_bytes)
        snapshots = payload["snapshots"]
        self.assertEqual([r["number"] for r in snapshots], [1, 2, 4, 7, 9, 11])
        self.assertEqual(
            snapshots, json.loads(json.dumps([asdict(r) for r in case.record.history]))
        )
        self.assertEqual(payload["selection"], {"revision": 7, "before": 11, "after": 4})
        self.assertEqual(payload["comparison"]["before"], 11)
        self.assertEqual(payload["comparison"]["after"], 4)
        self.assertTrue(payload["snapshot_observations"])
        self.assertEqual(payload["persisted_review"]["status"], "not_loaded")
        self.assertIsNone(payload["persisted_review"]["events"])
        self.assertEqual(payload["persisted_review"]["snapshot_link"], "not_established")
        self.assertIsNone(payload["review_conclusion"])
        self.assertIsNone(payload["scholarly_decision"])
        same = json.loads(self.packet(before="7", after="7")[1].json_bytes)
        self.assertFalse(same["comparison"]["changed"])

    def test_rejected_duplicate_and_pending_records_never_borrow_snapshots(self):
        packets = [
            json.loads(self.packet(key)[1].json_bytes)
            for key in ("batch-synthetic-csv-2", "batch-synthetic-json-1")
        ]
        self.assertEqual(
            packets[0]["identity"]["external_id"], packets[1]["identity"]["external_id"]
        )
        self.assertNotEqual(packets[0]["identity"], packets[1]["identity"])
        for payload in packets:
            self.assertEqual(payload["snapshots"], [])
            self.assertIsNone(payload["intake"]["prepared"])
            self.assertTrue(payload["preparation_errors"])
            self.assertTrue(payload["open_questions"])
        pending = json.loads(self.packet("batch-synthetic-csv-3")[1].json_bytes)
        self.assertIsNone(pending["comparison"])
        self.assertEqual(pending["receipt"]["intake_state"], "pending")

    def test_technical_diagnostics_keep_their_scope_and_unresolved_questions(self):
        payload = json.loads(self.packet(revision="1")[1].json_bytes)
        self.assertEqual(payload["reference_verification"]["scope"], "latest_fixture_snapshot")
        self.assertEqual(payload["reference_verification"]["revision"], 11)
        self.assertTrue(payload["open_questions"])
        self.assertTrue(all(q["action_ar"] for q in payload["open_questions"]))
        original = json.loads(self.packet("batch-synthetic-csv-1")[1].json_bytes)
        self.assertEqual(original["reference_verification"]["scope"], "original_intake")
        self.assertEqual(original["reference_verification"]["results"][0]["status"], "verified")
        self.assertEqual(
            original["reference_verification"]["results"][0]["evidence"],
            services.build_prepared_workbench().cases[0].references[0]["evidence"],
        )

    def test_explicit_empty_or_false_revision_ids_are_not_defaulted(self):
        from apps.revision_core.revision_history import InvalidRevisionId

        for selection in (
            {"revision": ""},
            {"before": "", "after": "7"},
            {"before": "7", "after": ""},
            {"revision": False},
        ):
            with self.subTest(selection=selection):
                with self.assertRaises(InvalidRevisionId):
                    self.packet(**selection)

    def test_serialization_is_bounded_strict_and_never_truncates(self):
        from apps.editorial_workbench.packets import PacketDataError, serialize_packet

        for invalid in (
            {"text": "\ud800"},
            {"number": float("nan")},
            {"extra": object()},
            {1: "bad key"},
            {"text": "x" * 131073},
            {"items": [None] * 4097},
        ):
            with self.subTest(invalid=type(next(iter(invalid.values()))).__name__):
                with self.assertRaises(PacketDataError):
                    serialize_packet(invalid)
        deep = {}
        for _ in range(20):
            deep = {"nested": deep}
        with self.assertRaises(PacketDataError):
            serialize_packet(deep)
        with self.assertRaises(PacketDataError):
            serialize_packet({str(i): "س" * 131072 for i in range(5)})

    def test_bad_provenance_fails_closed_without_external_io(self):
        from apps.editorial_workbench.packets import PacketDataError, build_packet

        prepared = services.build_prepared_workbench()
        case, batch = prepared.cases[0], prepared.batches[0]
        for bad_case, bad_batch in (
            (replace(case, payload_sha256="0" * 64), batch),
            (case, None),
            (case, prepared.batches[1]),
        ):
            with self.assertRaises(PacketDataError):
                build_packet(bad_case, bad_batch)
        with (
            patch("builtins.open", side_effect=AssertionError("file access")),
            patch("socket.socket", side_effect=AssertionError("network access")),
            patch(
                "apps.intake_workflow.review.load_review_worklist",
                side_effect=AssertionError("read"),
            ),
        ):
            self.assertEqual(
                build_packet(case, batch).json_bytes, build_packet(case, batch).json_bytes
            )
