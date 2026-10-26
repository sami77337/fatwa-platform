"""Actual FAST8 compositions on fixed fabricated records; no persisted authority."""

import base64
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from django.test import SimpleTestCase

from apps.editorial_export.services import build_export, encode_json
from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_workbench.batches import PreparedCase
from apps.editorial_workbench.packets import serialize_packet
from apps.editorial_workbench.services import build_prepared_workbench
from apps.fast6_journey.integration import run_integration
from apps.fast8_acceptance_evidence.services import build_report
from apps.fast8_case_permission.services import ContextError, describe_case, evaluate_case
from apps.fast8_case_references.services import build_dossier
from apps.fast8_fiqh_navigation.services import CatalogNavigation, CatalogSnapshot
from apps.fast8_intake_recovery.services import preview_recovery
from apps.fast8_journey_conformance.services import (
    AdapterEvidence,
    default_contract,
    run_conformance,
)
from apps.fast8_packet_verifier.services import PacketVerificationError, verify_packet
from apps.fast8_prepared_review.services import inspect_case
from apps.fast8_review_export.services import build_preview, verify_preview
from apps.fast8_segment_timeline.service import diagnose_file
from apps.fast8_source_preflight.service import verify_receipt
from apps.fast8_transcript_queue.services import build_transcript_queue
from apps.fiqh_reading_trail.services import ReadingTrail
from apps.reference_links.resolution import SnapshotCatalog
from tests.fast8_source_preflight.fixtures import AS_OF, fixture
from tools.fiqh_reading_trail.fixtures import EDITION_ID, synthetic_case, synthetic_fixture


class Fast8CompositionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalog = build_queue_catalog()
        cls.bundle = build_export(synthetic_fixtures_only=True)
        cls.files = dict(cls.bundle.files)
        cls.packets = {e["packet"]["identity"]["case_key"]: e for e in cls.bundle.report()["cases"]}

    def test_case_permission_dossier_packet_and_prepared_rows_share_complete_identity(self):
        original = asdict(self.catalog)
        for row in self.catalog.rows:
            key = row.case.key
            with self.subTest(key=key):
                packet = self.packets[key]
                dossier = build_dossier(key, synthetic_fixtures_only=True).payload()
                try:
                    descriptor = describe_case(key)
                except ContextError as exc:
                    expected_rejections = {
                        "intake-1": "DUPLICATE_EXTERNAL_ID",
                        "intake-4": "DUPLICATE_EXTERNAL_ID",
                        "intake-3": "ROW_BLOCKED",
                        "intake-5": "MISSING_OR_INVALID_EXTERNAL_ID",
                        "intake-6": "MISSING_OR_INVALID_EXTERNAL_ID",
                        "intake-8": "MISSING_OR_INVALID_EXTERNAL_ID",
                        "batch-synthetic-csv-2": "DUPLICATE_EXTERNAL_ID",
                        "batch-synthetic-csv-4": "ROW_BLOCKED",
                        "batch-synthetic-json-1": "DUPLICATE_EXTERNAL_ID",
                        "batch-synthetic-json-3": "ROW_BLOCKED",
                        "batch-synthetic-json-4": "MISSING_OR_INVALID_EXTERNAL_ID",
                        "batch-synthetic-jsonl-3": "ROW_BLOCKED",
                    }
                    self.assertEqual(str(exc), expected_rejections[key])
                    descriptor = None
                else:
                    decision = evaluate_case(
                        case_key=key, descriptor=descriptor, actor="MUFTI", action="read"
                    )
                    self.assertEqual(decision.context_status, "VERIFIED")
                    self.assertEqual(decision.effect, "DENY")
                    self.assertFalse(decision.allowed)
                    self.assertEqual(
                        descriptor.payload_sha256, packet["packet"]["source"]["input_sha256"]
                    )
                    self.assertEqual(descriptor.source_sha256, row.source_sha256)
                self.assertEqual(dossier["identity"], packet["packet"]["identity"])
                self.assertEqual(dossier["provenance"]["case_source_sha256"], row.source_sha256)
                self.assertEqual(dossier["provenance"]["packet_sha256"], packet["packet_sha256"])
                verified = json.loads(
                    verify_packet(
                        serialize_packet(packet["packet"]),
                        self.files["manifest.json"],
                        case_key=key,
                        synthetic_fixtures_only=True,
                    )
                )
                self.assertEqual(verified["packet_sha256"], packet["packet_sha256"])
                if isinstance(row.case, PreparedCase):
                    prepared = inspect_case(key, synthetic_fixtures_only=True)
                    identity = prepared["source_identity"]
                    for field in (
                        "case_key",
                        "batch_id",
                        "external_id",
                        "payload_sha256",
                        "row_ordinal",
                    ):
                        self.assertEqual(
                            identity[field],
                            getattr(row.case, "key" if field == "case_key" else field),
                        )
                    self.assertEqual(identity["parsed_row_sha256"], row.source_sha256)
                    self.assertTrue(
                        all(
                            join["status"] == "NOT_CONNECTED" for join in prepared["joins"].values()
                        )
                    )
        self.assertEqual(asdict(build_queue_catalog()), original)

    def test_duplicate_external_id_and_stale_row_cannot_join_or_authorize(self):
        for key in ("intake-1", "intake-4"):
            with self.assertRaisesRegex(ContextError, "^DUPLICATE_EXTERNAL_ID$"):
                describe_case(key)
        one, four = describe_case("batch-synthetic-csv-1"), describe_case("batch-synthetic-json-2")
        for key, descriptor in (
            (four.case_key, one),
            (one.case_key, replace(one, source_sha256=four.source_sha256)),
            (one.case_key, replace(one, payload_sha256="0" * 64)),
        ):
            decision = evaluate_case(
                case_key=key, descriptor=descriptor, actor="MUFTI", action="read"
            )
            self.assertEqual(decision.context_status, "REJECTED")
            self.assertFalse(decision.allowed)
        with self.assertRaises(PacketVerificationError):
            verify_packet(
                serialize_packet(self.packets["intake-1"]["packet"]),
                self.files["manifest.json"],
                case_key="intake-4",
                synthetic_fixtures_only=True,
            )

    def test_review_export_uses_original_packet_and_never_claims_persisted_review(self):
        original = self.files.copy()
        preview = build_preview(self.files, synthetic_fixtures_only=True)
        report = json.loads(preview.file("preview.json"))
        verify_preview(dict(preview.files), self.files, synthetic_fixtures_only=True)
        connected = [case for case in report["cases"] if case["association"] == "CONNECTED"]
        self.assertEqual([case["case_key"] for case in connected], ["intake-7"])
        case = connected[0]
        descriptor = describe_case(case["case_key"])
        self.assertEqual(case["packet_sha256"], self.packets[case["case_key"]]["packet_sha256"])
        self.assertEqual(case["source"]["text_sha256"], descriptor.source_sha256)
        self.assertEqual(case["source"]["input_sha256"], descriptor.payload_sha256)
        self.assertEqual(len(case["events"]), 6)
        self.assertEqual(report["persisted_review"], "NOT_CONNECTED")
        self.assertEqual(self.files, original)

    def test_transcript_timeline_and_ephemeral_queue_use_exact_same_spans(self):
        path = Path("tests/fast8_transcript_queue/fixtures/fabricated_spans.json")
        raw = path.read_bytes()
        queue = build_transcript_queue(raw, ".json", synthetic_fixtures_only=True)
        timeline = diagnose_file(raw, ".json", synthetic_fixtures_only=True)
        data = json.loads(timeline.json_bytes())
        cues = json.loads(timeline.cue_json_bytes())["cues"]
        self.assertEqual(data["input_sha256"], sha256(raw).hexdigest())
        self.assertEqual(data["contract_status"], "PASS")
        self.assertEqual(data["media_status"], "NOT_CONNECTED")
        sources = {s["source_id"]: s["source_sha256"] for s in data["sources"]}
        spans = {(s["source_id"], s["segment_id"]): s for s in data["segments"]}
        for entry, row in zip(queue.entries, queue.rows, strict=True):
            self.assertEqual(entry.input_sha256, data["input_sha256"])
            self.assertEqual(entry.source_sha256, sources[entry.source_id])
            self.assertEqual(
                entry.prepared_payload_sha256, sha256(queue.prepared_bytes()).hexdigest()
            )
            self.assertEqual(
                queue.resolve(entry.source_id, entry.pair_id, entry.source_sha256), entry
            )
            self.assertEqual(row.case.question, entry.question.text)
            self.assertEqual(row.source_sha256, entry.question.sha256)
            self.assertIsNone(row.case.record)
            for segment in (entry.question, entry.answer):
                if segment is not None:
                    span = spans[segment.source_id, segment.segment_id]
                    for field, value in asdict(segment).items():
                        self.assertEqual(span[field], value)
                    self.assertEqual(span["segment_sha256"], segment.sha256)
            cue = next(c for c in cues if c["segment_id"] == entry.question.segment_id)
            self.assertEqual(cue["question_label"], row.case.question)
            # Separate namespaces: never silently substitute a stock case.
            self.assertNotIn(row.case.key, self.packets)
        self.assertEqual(path.read_bytes(), raw)

    def test_recovery_keeps_input_bytes_and_duplicate_row_identity(self):
        batches = {b.batch_id: b for b in build_prepared_workbench().batches}
        recovery = json.loads(preview_recovery(batch_id="synthetic-csv", row=2).json_bytes())
        row = recovery["rows"][0]
        packet = self.packets["batch-synthetic-csv-2"]["packet"]
        self.assertEqual(row["batch_id"], packet["identity"]["batch_id"])
        self.assertEqual(row["row"], packet["identity"]["row_ordinal"])
        self.assertEqual(row["original"]["external_id"], packet["identity"]["external_id"])
        self.assertEqual(row["provenance"]["input_sha256"], packet["source"]["input_sha256"])
        source = batches[row["batch_id"]].raw_source.encode("utf-8")
        provenance = row["provenance"]
        self.assertEqual(
            source[provenance["byte_start"] : provenance["byte_end"]],
            base64.b64decode(provenance["raw_base64"]),
        )
        self.assertEqual(row["state"], "BLOCKED_INVALID")
        self.assertFalse(recovery["source_modification_performed"])
        self.assertFalse(recovery["resubmission_performed"])

    def test_dossier_and_fiqh_navigation_share_exact_edition_reference(self):
        prepared, headings = synthetic_fixture()
        catalog = SnapshotCatalog(headings)

        class FixedSyntheticReader:
            @contextmanager
            def snapshot(self, edition):
                yield CatalogSnapshot(edition, prepared, catalog)

        dossier = build_dossier(
            "intake-1",
            synthetic_fixtures_only=True,
            trail=ReadingTrail(prepared, EDITION_ID),
            catalog=catalog,
        ).payload()
        reference = dossier["references"][0]
        navigation = CatalogNavigation(prepared, EDITION_ID)
        query = {
            "edition": str(EDITION_ID),
            "source_row_id": str(reference["evidence"]["source_row_id"]),
        }
        result = navigation.from_reference(query, synthetic_case(), 1, FixedSyntheticReader())
        self.assertEqual(result.trail.status, "verified")
        self.assertEqual(result.trail.current.catalog_url, reference["catalog_url"])
        self.assertEqual(
            json.loads(encode_json(asdict(result.trail.current.evidence))), reference["evidence"]
        )
        self.assertEqual(navigation.navigate(query).trail.reason, "NOT_CONNECTED")

    def test_evidence_journey_and_real_case_probe_preserve_gaps_and_source_pins(self):
        upstream = run_integration(synthetic_fixtures_only=True)
        evidence = build_report(synthetic_fixtures_only=True).payload()
        artifact = evidence["artifacts"][0]
        self.assertEqual(artifact["sha256"], upstream.sha256)
        self.assertEqual(encode_json(artifact["payload"]), upstream.json_bytes)
        contract = json.loads(default_contract())
        contract["scenarios"] = [
            row for row in contract["scenarios"] if row["id"] == "batch-synthetic-csv-1"
        ]
        contract["scenarios"][0]["extensions"] = ["integrated_case_deny"]

        def case_probe(anchor):
            identity = json.loads(anchor.json_bytes)["identity"]
            descriptor = describe_case(identity["case_key"])
            self.assertEqual(descriptor.payload_sha256, identity["input_sha256"])
            decision = evaluate_case(
                case_key=identity["case_key"], descriptor=descriptor, actor="MUFTI", action="read"
            )
            self.assertEqual(decision.context_status, "VERIFIED")
            self.assertFalse(decision.allowed)
            return AdapterEvidence(anchor, "PASS")

        journey = run_conformance(
            encode_json(contract),
            synthetic_fixtures_only=True,
            probes={"integrated_case_deny": case_probe},
        ).payload()
        extension = journey["scenarios"][0]["extensions"][0]
        self.assertEqual((extension["status"], extension["execution"]), ("PASS", "RUN"))
        self.assertEqual(journey["permission"]["case_binding"], "NOT_CONNECTED")
        self.assertEqual(journey["execution"]["postgres"], "NOT_RUN")
        self.assertEqual(evidence["status"], "BLOCKED")
        raw, pin = fixture()
        source = verify_receipt(raw, expected_sha256=pin, as_of=AS_OF).as_dict()
        self.assertEqual(source["status"], "RECEIPT_VERIFIED")
        self.assertEqual(source["source_bytes"], "NOT_SUPPLIED")
        self.assertEqual(source["catalog_connection"], "NOT_CONNECTED")
        self.assertEqual(source["owner_acceptance"], "NOT_RUN")
