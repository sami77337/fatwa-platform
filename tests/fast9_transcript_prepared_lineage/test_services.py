import csv
import io
import json
import unittest
from hashlib import sha256
from unittest.mock import patch

from apps.fast8_segment_timeline.service import diagnose_file
from apps.fast8_transcript_queue.services import build_transcript_queue
from apps.fast9_transcript_prepared_lineage.services import (
    MAX_RECEIPT_BYTES,
    build_lineage,
    load_pins,
    verify_receipt,
)
from apps.fatwa_drafts.intake import ValidationError
from apps.prepared_pipeline import prepare_batch
from tests.fast9_transcript_prepared_lineage.support import FIXTURES, arguments, encode, rows


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.raw = (FIXTURES / "manual-qa.json").read_bytes()
        self.pins = load_pins((FIXTURES / "manual-qa.pins.json").read_bytes())
        self.kwargs = dict(
            expected_input_sha256=self.pins["input_sha256"],
            expected_sources=self.pins["sources"],
            synthetic_fixtures_only=True,
        )

    def test_checked_in_fixture_identity_and_crlf(self):
        self.assertEqual(json.loads(self.raw), rows())
        self.assertIn("\r\n", json.loads(self.raw)[0]["text"])
        self.assertEqual(sha256(self.raw).hexdigest(), self.pins["input_sha256"])
        self.assertEqual(arguments(self.raw), self.kwargs)

    def test_actual_services_join_exact_arabic_bytes_ids_timestamps_and_hashes(self):
        for suffix in (".json", ".jsonl", ".csv"):
            with self.subTest(suffix=suffix):
                raw = encode(rows(), suffix)
                result = build_lineage(raw, suffix, **arguments(raw, suffix))
                report = json.loads(result.json_bytes())
                queue = build_transcript_queue(raw, suffix, synthetic_fixtures_only=True)
                prepared = prepare_batch(queue.prepared_bytes(), synthetic_fixtures_only=True)
                timeline = diagnose_file(raw, suffix, synthetic_fixtures_only=True)
                self.assertEqual(result.prepared_bytes(), queue.prepared_bytes())
                self.assertEqual(result.cue_json_bytes(), timeline.cue_json_bytes())
                self.assertEqual(result.cue_csv_bytes(), timeline.cue_csv_bytes())
                self.assertEqual(
                    report["prepared_report_sha256"], sha256(prepared.json_bytes()).hexdigest()
                )
                self.assertEqual(
                    report["timeline_report_sha256"], sha256(timeline.json_bytes()).hexdigest()
                )
                self.assertEqual(
                    report["queue_report_sha256"], sha256(queue.json_bytes()).hexdigest()
                )
                self.assertEqual(len(report["receipts"]), 2)
                originals = {(r["source_id"], r["kind"]): r for r in rows()}
                for receipt, item in zip(report["receipts"], prepared.report["items"], strict=True):
                    self.assertEqual(receipt["prepared_item"], item)
                    for kind in ("question", "answer"):
                        evidence = receipt[kind]
                        original = originals[(receipt["source_id"], kind)]
                        self.assertEqual(evidence["segment"], original)
                        self.assertEqual(
                            evidence["text_utf8_sha256"],
                            sha256(original["text"].encode()).hexdigest(),
                        )
                        self.assertEqual(
                            evidence["manual_cue"]["segment_sha256"], evidence["segment_sha256"]
                        )
                        self.assertEqual(
                            evidence["manual_cue"]["source_sha256"], receipt["source_sha256"]
                        )
                        self.assertEqual(evidence["manual_cue"]["start_ms"], original["start_ms"])
                        self.assertEqual(evidence["manual_cue"]["end_ms"], original["end_ms"])
                        self.assertEqual(
                            evidence["manual_cue"]["start_time"],
                            "00:00:00.017" if kind == "question" else "00:00:01.023",
                        )
                self.assertEqual(len({r["receipt_id"] for r in report["receipts"]}), 2)
                csv_cues = list(
                    csv.DictReader(io.StringIO(result.cue_csv_bytes().decode(), newline=""))
                )
                self.assertEqual([r["question_label"] for r in csv_cues], [rows()[0]["text"]] * 4)

    def test_no_fixed_case_or_django_or_network_access_and_no_draft(self):
        with (
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
            patch(
                "apps.editorial_workbench.services.build_prepared_workbench",
                side_effect=AssertionError("stock cases forbidden"),
            ),
            patch(
                "apps.prepared_pipeline.create_draft", side_effect=AssertionError("draft forbidden")
            ),
        ):
            report = json.loads(build_lineage(self.raw, ".json", **self.kwargs).json_bytes())
        self.assertEqual(report["storage"], "EPHEMERAL")
        self.assertEqual(report["draft_count"], 0)
        self.assertFalse(report["answer_exported"])
        self.assertFalse(report["publication_allowed"])
        self.assertEqual(report["answer_role"], "SOURCE_EVIDENCE_ONLY")
        for key in ("media", "fixed_cases", "catalog", "policy", "source_owner", "production"):
            self.assertEqual(report["connections"][key], "NOT_CONNECTED")
        self.assertEqual(report["gates"]["B"], "NOT_PASSED")
        self.assertEqual(report["gates"]["Phase01"], "BLOCKED")
        self.assertTrue(any(f["code"] == "gap" for f in report["timeline_findings"]))

    def test_missing_synthetic_attestation(self):
        for flag in (False, None, 1, "true"):
            with (
                self.subTest(flag=flag),
                self.assertRaisesRegex(ValidationError, "acknowledgement"),
            ):
                build_lineage(
                    self.raw, ".json", **(self.kwargs | {"synthetic_fixtures_only": flag})
                )

    def test_raw_input_tampering_and_file_crlf_drift_fail_before_composition(self):
        original = encode(rows())
        kwargs = arguments(original)
        for changed in (
            original + b" ",
            original.replace(b"\r\n", b"\n"),
            original.replace(b"1017", b"1018"),
        ):
            with (
                self.subTest(changed=sha256(changed).hexdigest()),
                patch(
                    "apps.fast9_transcript_prepared_lineage.services.build_transcript_queue",
                    side_effect=AssertionError("must reject before composition"),
                ),
                self.assertRaisesRegex(ValidationError, "input_pin_mismatch"),
            ):
                build_lineage(changed, ".json", **kwargs)

    def test_stale_source_even_if_caller_updates_file_pin(self):
        for field, value in (
            ("text", "نص مختلق مختلف"),
            ("start_ms", 18),
            ("provenance", "changed synthetic provenance"),
        ):
            changed = rows()
            changed[0][field] = value
            raw = encode(changed)
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValidationError, "stale_or_incomplete"),
            ):
                build_lineage(
                    raw,
                    ".json",
                    **(self.kwargs | {"expected_input_sha256": sha256(raw).hexdigest()}),
                )

    def test_crlf_inside_text_changes_source_revision(self):
        changed = rows()
        changed[1]["text"] = changed[1]["text"].replace("\r\n", "\n")
        raw = encode(changed)
        with self.assertRaisesRegex(ValidationError, "stale_or_incomplete"):
            build_lineage(
                raw, ".json", **(self.kwargs | {"expected_input_sha256": sha256(raw).hexdigest()})
            )

    def test_source_set_must_match_exactly(self):
        for sources in (
            {"absent": "0" * 64},
            dict(self.pins["sources"], extra="0" * 64),
            {"fabricated-source-b": self.pins["sources"]["fabricated-source-b"]},
        ):
            with (
                self.subTest(sources=sources),
                self.assertRaisesRegex(ValidationError, "stale_or_incomplete"),
            ):
                build_lineage(self.raw, ".json", **(self.kwargs | {"expected_sources": sources}))

    def test_missing_answer_rejected_even_with_valid_new_source_pins(self):
        raw = encode(rows()[:-1])
        with self.assertRaisesRegex(ValidationError, "answer_required"):
            build_lineage(raw, ".json", **arguments(raw))

    def test_invalid_spans_fail_closed(self):
        mutations = (
            (1, "start_ms", 1000),
            (1, "segment_id", rows()[0]["segment_id"]),
            (1, "kind", "question"),
            (0, "kind", "answer"),
            (0, "start_ms", True),
            (0, "end_ms", 1.5),
            (0, "fabricated", False),
            (0, "text", ""),
            (0, "pair_id", "another-pair"),
        )
        for index, field, value in mutations:
            changed = rows()
            changed[index][field] = value
            raw = encode(changed)
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                build_lineage(
                    raw,
                    ".json",
                    **(self.kwargs | {"expected_input_sha256": sha256(raw).hexdigest()}),
                )

    def test_unordered_input_preserves_exact_timings_without_guessing(self):
        raw = encode(list(reversed(rows())))
        result = build_lineage(raw, ".json", **arguments(raw))
        report = json.loads(result.json_bytes())
        self.assertTrue(any(f["code"] == "input_order" for f in report["timeline_findings"]))
        self.assertEqual(
            [r["answer"]["segment"]["start_ms"] for r in report["receipts"]], [1023, 1023]
        )

    def test_receipt_replay_is_exact_and_rejects_changes_to_every_stage(self):
        result = build_lineage(self.raw, ".json", **self.kwargs)
        self.assertEqual(
            verify_receipt(result.json_bytes(), self.raw, ".json", **self.kwargs), result
        )
        report = json.loads(result.json_bytes())
        changed_payloads = [result.json_bytes() + b" ", result.json_bytes().replace(b"\n", b"\r\n")]
        for path, value in (
            (("source_sha256",), "0" * 64),
            (("pair_id",), "unrelated"),
            (("question", "segment", "text"), "نص مختلق مختلف"),
            (("answer", "manual_cue", "start_ms"), 0),
            (("prepared_item", "original", "external_id"), "stock-case-1"),
        ):
            changed = json.loads(result.json_bytes())
            target = changed["receipts"][0]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            changed_payloads.append(json.dumps(changed, ensure_ascii=False).encode())
        for changed in changed_payloads:
            with (
                self.subTest(digest=sha256(changed).hexdigest()),
                self.assertRaisesRegex(ValidationError, "receipt_bytes_mismatch"),
            ):
                verify_receipt(changed, self.raw, ".json", **self.kwargs)
        report["receipts"].clear()
        self.assertEqual(
            result.json_bytes(), build_lineage(self.raw, ".json", **self.kwargs).json_bytes()
        )

    def test_invalid_input_and_receipt_bounds(self):
        for raw in (b"", "text", b"x" * 1_000_001):
            with self.subTest(size=len(raw)), self.assertRaises(ValidationError):
                build_lineage(raw, ".json", **self.kwargs)
        for raw in (b"", "text", b"x" * (MAX_RECEIPT_BYTES + 1)):
            with self.subTest(size=len(raw)), self.assertRaises(ValidationError):
                verify_receipt(raw, self.raw, ".json", **self.kwargs)

    def test_pin_parser_rejects_ambiguous_and_invalid_manifests(self):
        valid = (FIXTURES / "manual-qa.pins.json").read_bytes()
        for raw in (
            b"",
            b"null",
            b"\xff",
            b'{"schema":1,"schema":2}',
            valid.replace(b'"input_sha256"', b'"unexpected"'),
        ):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValidationError):
                load_pins(raw)
        for field, value in (
            ("sources", {}),
            ("sources", []),
            ("input_sha256", "A" * 64),
            ("input_sha256", False),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                load_pins(json.dumps(self.pins | {field: value}).encode())
