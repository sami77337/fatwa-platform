"""Pure workbench composition over invented local fixtures; no database required."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.editorial_demo.revision_fixtures import REVISION_HISTORY_RECORD
from apps.fatwa_drafts.intake import serialize_intake
from apps.intake_workflow import contracts as c
from apps.intake_workflow import fixtures
from apps.reference_links.diagnostics import build_reference_diagnostics
from apps.reference_links.resolution import Heading


class WorkbenchCaseTests(SimpleTestCase):
    def service(self):
        # A missing adapter is the initial red behavior, before implementation.
        try:
            from apps.editorial_workbench import services
        except ImportError:
            self.fail("The connected local workbench case adapter is not implemented")

        return services

    def test_all_original_rows_keep_exact_unicode_slices_and_payload_digest(self):
        service = self.service()
        raw = fixtures.synthetic_payload()
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        cases = service.build_cases()
        self.assertEqual(
            [case.key for case in cases],
            ["history", *[f"intake-{number}" for number in range(1, 9)]],
        )
        for case, source, original in zip(
            cases[1:], parsed.item_sources, parsed.items, strict=True
        ):
            self.assertEqual(case.raw_source.encode("utf-8"), raw[source.start : source.end])
            self.assertEqual((case.source_start, case.source_end), (source.start, source.end))
            self.assertEqual(case.payload_sha256, sha256(raw).hexdigest())
            question = original.get("question") if isinstance(original, dict) else None
            self.assertEqual(case.question, question)
        self.assertEqual(cases[1].question, "  سُؤَالٌ اصطناعي\tبِعلاماته\nوسطره  ")
        self.assertEqual(cases[-1].raw_source, "null")
        self.assertIsNone(cases[-1].external_id)
        self.assertIsNone(cases[-1].question)

    def test_duplicate_invalid_and_null_rows_stay_visible_without_drafts(self):
        cases = self.service().build_cases()[1:]
        self.assertEqual(
            [case.status for case in cases],
            ["blocked", "review", "blocked", "blocked", "blocked", "blocked", "ready", "blocked"],
        )
        self.assertEqual(cases[0].external_id, cases[3].external_id)
        self.assertNotEqual(cases[0].question, cases[3].question)
        self.assertEqual(cases[4].external_id, "BAD\tID")
        self.assertIsNone(cases[5].external_id)
        for case in cases:
            if case.status == "blocked":
                self.assertIsNone(case.record)
                self.assertTrue(case.issues)
        self.assertIsNone(cases[1].record)
        self.assertIsNone(cases[1].prepared_clip_url)
        self.assertEqual(cases[2].prepared_clip_url, "http://example.invalid/x")

    def test_ready_record_retains_exact_question_and_empty_receipt_revision(self):
        case = self.service().build_cases()[7]
        record = case.record
        self.assertIsNotNone(record)
        self.assertEqual(record.intake.external_id, "W7-READY-2")
        self.assertEqual(record.intake.question, case.question)
        self.assertEqual(record.intake.prepared_clip_url, case.prepared_clip_url)
        self.assertEqual(
            asdict(record.intake.reference_links[0]),
            {**c.SOURCE_IDENTITY, "source_id": "wave7-title-2"},
        )
        self.assertEqual(len(record.history), 1)
        self.assertEqual(record.current.action, "received")
        self.assertEqual(record.current.title, "")
        self.assertEqual(record.current.answer, "")
        self.assertEqual(record.current.reviewer_notes, "")

    def test_history_reuses_exact_intake_and_revision_objects_with_serialized_provenance(self):
        case = self.service().build_cases()[0]
        self.assertIs(case.record, REVISION_HISTORY_RECORD)
        self.assertIs(case.record.intake, REVISION_HISTORY_RECORD.intake)
        for displayed, original in zip(
            case.record.history, REVISION_HISTORY_RECORD.history, strict=True
        ):
            self.assertIs(displayed, original)
        serialized = serialize_intake((REVISION_HISTORY_RECORD.intake,))
        self.assertEqual(case.raw_source.encode("utf-8"), serialized)
        self.assertEqual(case.payload_sha256, sha256(serialized).hexdigest())
        self.assertIsNone(case.source_start)
        self.assertIsNone(case.source_end)
        self.assertIn("تسلسل", case.fixture_label)
        self.assertEqual(case.status, "review")

    def test_history_reference_identities_are_complete_and_never_claim_verified_evidence(self):
        case = self.service().build_cases()[0]
        expected = [asdict(ref) for ref in REVISION_HISTORY_RECORD.current.reference_links]
        self.assertEqual([ref["original_identity"] for ref in case.references], expected)
        for ref in case.references:
            self.assertEqual(ref["status"], "unresolved")
            self.assertEqual(ref["verified_identity"], {})
            self.assertIsNone(ref["evidence"])
            self.assertTrue(ref["reasons"])
            self.assertRegex(ref["explanation_ar"], r"[؀-ۿ]")
            self.assertRegex(ref["verification_limit_ar"], r"[؀-ۿ]")

    def test_wave7_references_equal_existing_diagnostics_on_exact_original_bytes(self):
        cases = self.service().build_cases()[1:]
        root = "كِتَابٌ اصطناعي"
        headings = tuple(
            Heading(
                7001,
                row,
                "مرجع اصطناعي لتجارب Wave7",
                title,
                "الأول",
                6 + row,
                (root,) if row == 1 else (root, title),
                c.SOURCE_IDENTITY["source_namespace"],
                "622",
                c.SOURCE_IDENTITY["source_input_sha256"],
                c.SOURCE_IDENTITY["edition_key"],
                c.SOURCE_IDENTITY["source_archive_sha256"],
            )
            for row, title in [(1, root), (2, "بابٌ اصطناعي أول"), (3, "بابٌ اصطناعي ثان")]
        )
        expected = build_reference_diagnostics(
            fixtures.synthetic_payload(), synthetic_fixtures_only=True, catalog_rows=headings
        ).to_payload()["items"]
        for case, item in zip(cases, expected, strict=True):
            self.assertEqual(case.references, tuple(item["references"]))
        self.assertEqual(cases[0].references[0]["status"], "verified")
        self.assertEqual(cases[0].status, "blocked")
        self.assertEqual(
            cases[6].references[0]["verified_identity"], dict(c.VERIFIED_IDENTITIES[1])
        )

    def test_real_planner_retains_unmapped_mismatched_and_duplicate_pointer_decisions(self):
        service = self.service()
        links = [
            {"source_id": "unknown", "heading_id": "unknown"},
            {**c.SOURCE_IDENTITY, "source_id": "wave7-title-1", "edition_key": "other"},
            {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"},
            {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"},
        ]
        raw = json.dumps(
            {
                "schema": c.PAYLOAD_SCHEMA,
                "synthetic_fixtures_only": True,
                "items": [
                    {
                        "external_id": "SYN-UNRESOLVED",
                        "question": "  نصٌ\nمحفوظ  ",
                        "prepared_clip_url": "https://example.invalid/test",
                        "reference_links": links,
                    }
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        with patch.object(fixtures, "synthetic_payload", return_value=raw):
            case = service.build_cases()[1]
        self.assertEqual(
            [ref["status"] for ref in case.references],
            ["unresolved", "mismatched", "unresolved", "unresolved"],
        )
        self.assertEqual(
            [ref["reasons"] for ref in case.references],
            [
                ["explicit_mapping_missing"],
                ["source_identity_mismatch"],
                ["duplicate_pointer"],
                ["duplicate_pointer"],
            ],
        )
        self.assertIsNone(case.record)
        for ref in case.references:
            source = ref["source"]
            self.assertEqual(source["text"].encode(), raw[source["start"] : source["end"]])

    def test_fresh_builds_do_not_share_mutable_reference_containers(self):
        service = self.service()
        first, second = service.build_cases(), service.build_cases()
        self.assertEqual(first, second)
        self.assertIsNot(first[1], second[1])
        first[1].references[0]["verified_identity"]["source_id"] = "changed"
        first[0].references[0]["original_identity"]["source_id"] = "changed"
        third = service.build_cases()
        self.assertEqual(second, third)
        with self.assertRaises(FrozenInstanceError):
            third[1].question = "changed"

    def test_adapter_requires_no_file_network_or_database_access(self):
        service = self.service()
        # Load pure dependencies before guards, then forbid external boundaries.
        service.build_cases()
        from django.db.backends.base.base import BaseDatabaseWrapper

        with (
            patch("builtins.open", side_effect=AssertionError("file access")),
            patch("socket.socket", side_effect=AssertionError("network access")),
            patch.object(
                BaseDatabaseWrapper, "connect", side_effect=AssertionError("database access")
            ),
            patch.object(
                BaseDatabaseWrapper, "cursor", side_effect=AssertionError("database query")
            ),
        ):
            self.assertEqual(len(service.build_cases()), 9)

    def test_expected_bad_data_is_wrapped_but_system_bugs_propagate(self):
        service = self.service()
        with patch.object(fixtures, "synthetic_payload", return_value=b"not-json"):
            with self.assertRaises(service.WorkbenchDataError):
                service.build_cases()
        with patch.object(fixtures, "synthetic_payload", side_effect=RuntimeError("system bug")):
            with self.assertRaisesRegex(RuntimeError, "system bug"):
                service.build_cases()
