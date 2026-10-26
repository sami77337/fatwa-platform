import json
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
from hashlib import sha256
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.editorial_workbench.packets import CaseReviewPacket, build_packet, serialize_packet
from apps.fast8_case_references.services import DossierError, _compose, build_dossier
from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference_links.resolution import CatalogReadError, SnapshotCatalog, resolve
from apps.reference_triage.services import _reference, build_investigation
from apps.research_bridge.services import BridgeResult
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_case, synthetic_fixture


class DossierTests(TestCase):
    def setUp(self):
        self.prepared, self.headings = synthetic_fixture()
        self.trail = ReadingTrail(self.prepared, EDITION_ID)
        self.catalog = SnapshotCatalog(self.headings)
        self.case = synthetic_case()
        self.packet = build_packet(self.case.case)

    def dossier(self, key="intake-1", **changes):
        options = dict(synthetic_fixtures_only=True, trail=self.trail, catalog=self.catalog)
        options.update(changes)
        return build_dossier(key, **options)

    def assert_closed(self, result, reason):
        entry = result.payload()["references"][0]
        self.assertNotEqual(entry["status"], "VERIFIED")
        self.assertEqual(entry["reason"], reason)
        for field in (
            "evidence",
            "verified_identity",
            "catalog_url",
            "reading_trail",
            "citation_html_text",
        ):
            self.assertIsNone(entry[field], field)

    def test_matched_exact_work_edition_row_location_ordinal_and_provenance(self):
        result = self.dossier().payload()
        self.assertEqual(result["status"], "VERIFIED")
        ref = result["references"][0]
        self.assertEqual(ref["reference_ordinal"], 1)
        expected = asdict(self.headings[0])
        expected["path"] = list(expected["path"])
        self.assertEqual(ref["evidence"], expected)
        self.assertEqual(ref["catalog_url"], "/fiqh/nodes/1?edition=7001")
        self.assertEqual(result["provenance"]["packet_sha256"], self.packet.sha256)
        self.assertEqual(ref["provenance"]["source_sha256"], self.case.references[0].source_sha256)
        self.assertEqual(result["verified_count"], 1)

    def test_no_raw_source_question_clip_answer_or_snapshot_export(self):
        dossier = self.dossier()
        payload = dossier.payload()
        forbidden = {
            "input_text",
            "text",
            "raw_source",
            "source_text",
            "question",
            "answer",
            "prepared_clip_url",
            "snapshots",
        }

        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        self.assertNotIn(self.case.case.question.encode("utf-8"), dossier.json_bytes)

    def test_missing_occurrences_are_explicit_and_do_not_read_catalog(self):
        catalog = Mock()
        result = self.dossier("intake-2", catalog=catalog).payload()
        self.assertEqual(result["status"], "MISSING")
        self.assertEqual(result["missing_reason"], "no_reference_occurrences")
        self.assertEqual(result["references"], [])
        catalog.lookup.assert_not_called()

    def test_unresolved_history_preserves_every_reason_and_verification_scope(self):
        catalog = Mock()
        result = self.dossier("history", catalog=catalog).payload()
        case = next(row for row in build_investigation().cases if row.case.key == "history")
        self.assertEqual(result["provenance"]["verification_scope"], "latest_fixture_snapshot")
        self.assertEqual(
            result["provenance"]["verification_revision"], case.case.record.current.number
        )
        self.assertEqual([r["reference_ordinal"] for r in result["references"]], [1, 2, 3])
        for ref, original in zip(result["references"], case.references, strict=True):
            self.assertEqual(ref["unresolved_reasons"], list(original.reasons))
            self.assertEqual(ref["explanation_ar"], original.explanation)
        catalog.lookup.assert_not_called()

    def test_all_fixed_cases_preserve_every_unresolved_occurrence(self):
        for case in build_investigation().cases:
            result = self.dossier(case.case.key).payload()
            self.assertEqual(result["reference_count"], len(case.references))
            for ref, original in zip(result["references"], case.references, strict=True):
                self.assertEqual(ref["upstream_status"], original.raw_status)
                self.assertEqual(ref["unresolved_reasons"], list(original.reasons))
                if original.status != "verified":
                    self.assertIsNone(ref["catalog_url"])

    def fabricated_case(self, pointer):
        """Explicitly fabricated input; decisions come from the existing resolver."""
        case = next(row for row in build_investigation().cases if row.case.key == "history")
        source = json.dumps(pointer, ensure_ascii=False) + "\r\n"
        decision = resolve(pointer, SnapshotCatalog(()))
        raw = {
            "reference_ordinal": 1,
            "status": decision.outcome.value,
            "contract_status": "UNVERIFIED",
            "original_identity": pointer,
            "source": {"text": source, "start": None, "end": None},
            "reasons": list(decision.reasons),
            "explanation_ar": "اختبار اصطناعي فقط: إحالة غير محسومة.",
            "reason_explanations_ar": [],
            "verified_identity": {},
            "evidence": None,
        }
        workbench = replace(
            case.case,
            raw_source=source,
            payload_sha256=sha256(source.encode()).hexdigest(),
            record=None,
            references=(raw,),
        )
        return replace(
            case,
            case=workbench,
            references=(_reference(raw, 1),),
            source_sha256=sha256(source.encode()).hexdigest(),
        )

    def test_forbidden_and_missing_pointer_reasons_survive_without_raw_links(self):
        for pointer, reason in (
            ({"url": "javascript:synthetic-forbidden"}, "unknown_fields"),
            ({}, "exact_identity_required"),
        ):
            case = self.fabricated_case(pointer)
            catalog = Mock()
            result = _compose(case, build_packet(case.case), trail=self.trail, catalog=catalog)
            self.assertEqual(result.payload()["reference_count"], 1)
            self.assertEqual(result.payload()["references"][0]["unresolved_reasons"], [reason])
            self.assert_closed(result, "upstream_unverified")
            self.assertNotIn(b"javascript:", result.json_bytes)
            catalog.lookup.assert_not_called()

    def test_missing_catalog_does_not_use_django_default(self):
        with patch(
            "apps.reference_links.django_adapter.DjangoCatalog.lookup", side_effect=AssertionError
        ):
            self.assert_closed(self.dossier(catalog=None), "catalog_not_supplied")

    def test_missing_topology_remains_disconnected(self):
        self.assert_closed(self.dossier(trail=None), "reading_trail_not_supplied")

    def test_prepared_case_unsupported_trail_is_not_fabricated(self):
        # Prepared fixtures currently use independent source pins; their bridge
        # may close before the unsupported trail boundary. Neither creates a URL.
        for key in ("batch-synthetic-json-1", "batch-synthetic-csv-1"):
            result = self.dossier(key).payload()
            self.assertEqual(result["verified_count"], 0)
            self.assertIsNone(result["references"][0]["reading_trail"])

    def test_bridge_verified_prepared_case_explicitly_reports_unsupported_trail(self):
        # Isolate the adapter boundary; this stub is not source acceptance.
        bridge = BridgeResult("verified", "exact_catalog_match", "synthetic test", self.headings[0])
        with patch("apps.fast8_case_references.services.bridge_reference", return_value=bridge):
            result = self.dossier("batch-synthetic-json-1")
        self.assert_closed(result, "prepared_case_trail_unsupported")
        self.assertEqual(result.payload()["references"][0]["status"], "NOT_CONNECTED")

    def test_missing_exact_catalog_row(self):
        self.assert_closed(self.dossier(catalog=SnapshotCatalog(())), "identity_not_found")

    def test_duplicate_exact_candidates_fail_closed(self):
        self.assert_closed(
            self.dossier(catalog=SnapshotCatalog((*self.headings, self.headings[0]))),
            "multiple_exact_candidates",
        )

    def test_mismatched_identity_metadata_and_pins_fail_closed(self):
        for field, value in (
            ("work_title", "مرجع آخر"),
            ("heading_title", "عنوان آخر"),
            ("printed_part", "الثاني"),
            ("printed_page", 77),
            ("edition_key", "different-edition"),
            ("source_archive_sha256", "c" * 64),
            ("source_input_sha256", "d" * 64),
            ("source_namespace", "different-source"),
        ):
            with self.subTest(field=field):
                headings = (replace(self.headings[0], **{field: value}), *self.headings[1:])
                result = self.dossier(catalog=SnapshotCatalog(headings)).payload()
                self.assertEqual(result["verified_count"], 0)
                self.assertIsNone(result["references"][0]["catalog_url"])

    def test_missing_neighbor_closes_the_entire_citation(self):
        self.assert_closed(
            self.dossier(catalog=SnapshotCatalog(self.headings[:1])), "identity_not_found"
        )

    def test_reordered_catalog_storage_does_not_reorder_evidence(self):
        first = self.dossier()
        second = self.dossier(catalog=SnapshotCatalog(tuple(reversed(self.headings))))
        self.assertEqual(first.json_bytes, second.json_bytes)

    def test_reordered_occurrences_are_rejected_before_reads(self):
        case = next(row for row in build_investigation().cases if row.case.key == "history")
        packet = build_packet(case.case)
        altered = replace(case, references=tuple(reversed(case.references)))
        catalog = Mock()
        with self.assertRaisesRegex(DossierError, "reference_order_mismatch"):
            _compose(altered, packet, trail=self.trail, catalog=catalog)
        catalog.lookup.assert_not_called()

    def test_cross_case_packet_is_rejected_even_for_same_reference(self):
        other = next(row for row in build_investigation().cases if row.case.key == "intake-4")
        with self.assertRaisesRegex(DossierError, "packet_case_mismatch"):
            _compose(self.case, build_packet(other.case), trail=self.trail, catalog=self.catalog)

    def test_packet_tampering_is_rejected_without_export(self):
        for field, value in (
            ("case_key", "intake-4"),
            ("input_sha256", "0" * 64),
            ("source_start", True),
        ):
            payload = self.packet.payload()
            payload["identity"][field] = value
            with self.subTest(field=field), self.assertRaises(DossierError):
                _compose(self.case, CaseReviewPacket(serialize_packet(payload)))

    def test_source_digest_batch_and_reference_binding_are_strict(self):
        for altered in (
            replace(self.case, source_sha256="0" * 64),
            replace(self.case, batch_id="another-batch"),
            replace(self.case, references=()),
            replace(self.case, references=(replace(self.case.references[0], source_start=True),)),
            replace(
                self.case, references=(replace(self.case.references[0], verified_identity="{}"),)
            ),
            replace(self.case, references=(replace(self.case.references[0], ordinal=True),)),
        ):
            with self.subTest(altered=altered.batch_id), self.assertRaises(DossierError):
                _compose(altered, self.packet)

    def test_numeric_aliases_from_custom_adapter_fail_closed(self):
        for field, value in (
            ("source_row_id", True),
            ("source_row_id", 1.0),
            ("edition_id", 7001.0),
            ("printed_page", 7.0),
        ):
            catalog = Mock()
            catalog.lookup.return_value = (replace(self.headings[0], **{field: value}),)
            with self.subTest(field=field, value=value):
                self.assert_closed(self.dossier(catalog=catalog), "catalog_unavailable")

    def test_catalog_unavailable_has_no_citation(self):
        catalog = Mock()
        catalog.lookup.side_effect = CatalogReadError("private diagnostic must not be exported")
        self.assert_closed(self.dossier(catalog=catalog), "catalog_unavailable")

    def test_changed_catalog_between_bridge_and_trail_fails_closed(self):
        catalog = Mock()
        catalog.lookup.side_effect = [
            (self.headings[0],),
            (replace(self.headings[0], printed_page=88),),
        ]
        self.assert_closed(self.dossier(catalog=catalog), "catalog_evidence_mismatch")

    def test_output_is_deterministic_immutable_and_unicode_exact(self):
        before = self.packet.json_bytes
        first, second = self.dossier(), self.dossier()
        self.assertEqual(first.json_bytes, second.json_bytes)
        self.assertEqual(first.sha256, sha256(first.json_bytes).hexdigest())
        self.assertEqual(self.packet.json_bytes, before)
        self.assertIn(self.headings[0].heading_title.encode("utf-8"), first.json_bytes)
        payload = first.payload()
        payload["references"].clear()
        self.assertEqual(first.payload()["reference_count"], 1)
        with self.assertRaises(FrozenInstanceError):
            first.json_bytes = b"changed"

    def test_crlf_combining_text_preserved_in_binding_but_not_exported(self):
        row = self.fabricated_case({"synthetic_marker": "عَرَبِيّ e\u0301"})
        packet = build_packet(row.case)
        before = packet.json_bytes
        result = _compose(row, packet).payload()
        self.assertEqual(
            result["provenance"]["case_source_sha256"],
            sha256(row.case.raw_source.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("raw_source", result)
        self.assertTrue(row.case.raw_source.endswith("\r\n"))
        self.assertIn("e\u0301", packet.payload()["source"]["text"])
        self.assertEqual(packet.json_bytes, before)

    def test_opt_in_exact_case_selection_and_contract_types(self):
        for options in (
            {},
            {"synthetic_fixtures_only": 1},
            {"synthetic_fixtures_only": True, "trail": object()},
            {"synthetic_fixtures_only": True, "catalog": object()},
        ):
            with self.subTest(options=options), self.assertRaises(DossierError):
                build_dossier("intake-1", **options)
        for key in ("W7-VALID-1", "../intake-1", "", True, "x" * 101):
            with self.subTest(key=key), self.assertRaises(DossierError):
                self.dossier(key)

    def test_service_is_offline_and_does_not_mutate_inputs(self):
        before = asdict(self.prepared)
        with ExitStack() as stack:
            for target in (
                "builtins.open",
                "pathlib.Path.open",
                "socket.socket",
                "subprocess.Popen",
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            ):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            result = self.dossier()
        self.assertEqual(result.payload()["status"], "VERIFIED")
        self.assertEqual(asdict(self.prepared), before)

    def test_governance_holds_remain_exact(self):
        self.assertEqual(
            self.dossier().payload()["holds"],
            [
                "Gate B NOT_PASSED",
                "C/D/E HOLD",
                "Phase01 BLOCKED",
                "SCOPE_DEVIATION_HOLD",
                "NOT_DEPLOYED",
                "U03/U10 OWNER_APPROVAL_PENDING",
            ],
        )
