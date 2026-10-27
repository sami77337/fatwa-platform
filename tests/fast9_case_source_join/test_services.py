import json
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_workbench.packets import CaseReviewPacket, build_packet, serialize_packet
from apps.fast8_fiqh_navigation.services import CatalogSnapshot
from apps.fast9_case_source_join.services import JoinRequest, join_case_source
from apps.reference.records import prepare_catalog
from apps.reference_links.resolution import CatalogReadError, SnapshotCatalog
from apps.reference_triage.services import build_investigation
from tools.fast9_case_source_join.fixtures import synthetic_fixture
from tools.fiqh_reading_trail.fixtures import synthetic_fixture as unrelated_fixture


class Reader:
    def __init__(self, prepared, headings, edition=7001):
        self.value = CatalogSnapshot(edition, prepared, SnapshotCatalog(headings))
        self.active = False
        self.calls = 0

    @contextmanager
    def snapshot(self, edition):
        self.calls += 1
        self.active = True
        try:
            yield self.value
        finally:
            self.active = False


class JoinTests(TestCase):
    def setUp(self):
        self.case = next(c for c in build_investigation().cases if c.case.key == "intake-1")
        self.packet = build_packet(self.case.case)
        self.prepared, self.headings = synthetic_fixture()
        self.reader = Reader(self.prepared, self.headings)
        self.request = JoinRequest(
            case_key="intake-1",
            packet_sha256=self.packet.sha256,
            row_sha256=self.case.source_sha256,
            reference_ordinal=1,
            occurrence_sha256=self.case.references[0].source_sha256,
            catalog_checksum=self.prepared.checksum,
            edition_id=7001,
            source_row_id=1,
            source_id="wave7-title-1",
        )

    def join(self, **changes):
        options = dict(
            request=self.request,
            packet=self.packet,
            prepared=self.prepared,
            reader=self.reader,
            synthetic_fixtures_only=True,
        )
        options.update(changes)
        return join_case_source(**options).payload()

    def closed(self, result, status="REJECTED", reason=None):
        self.assertEqual(result["status"], status)
        if reason:
            self.assertEqual(result["reason"], reason)
        self.assertIsNone(result["join"])
        self.assertEqual(result["owner_source"], "NOT_CONNECTED")

    def test_complete_original_case_and_catalog_join_without_remapping(self):
        result = self.join()
        self.assertEqual(result["status"], "VERIFIED_TECHNICAL")
        joined = result["join"]
        self.assertEqual(joined["source_record"]["source_id"], "wave7-title-1")
        self.assertEqual(joined["evidence"]["heading_title"], "كِتَابٌ اصطناعي")
        self.assertEqual(joined["evidence"]["printed_part"], "الأول")
        self.assertEqual(joined["evidence"]["printed_page"], 7)
        self.assertEqual(joined["edition_title"], "طبعة اصطناعية")
        self.assertEqual(joined["provenance"]["row_sha256"], self.case.source_sha256)
        self.assertEqual(joined["provenance"]["catalog_checksum"], self.prepared.checksum)
        self.assertEqual(
            joined["original_identity"], {"source_id": "W7-SOURCE", "heading_id": "W7-HEADING-1"}
        )
        self.assertEqual(self.reader.calls, 1)
        self.assertFalse(self.reader.active)

    def test_unrelated_stock_navigation_fixture_is_never_mapped_to_case(self):
        prepared, headings = unrelated_fixture()
        result = self.join(
            prepared=prepared,
            reader=Reader(prepared, headings),
            request=replace(self.request, catalog_checksum=prepared.checksum),
        )
        self.closed(result, reason="source_id_mismatch")

    def test_cross_case_same_pointer_cannot_reuse_packet_or_row_hash(self):
        other = next(c for c in build_investigation().cases if c.case.key == "intake-4")
        packet = build_packet(other.case)
        self.closed(
            self.join(packet=packet, request=replace(self.request, packet_sha256=packet.sha256))
        )
        self.closed(self.join(request=replace(self.request, case_key="intake-4")))
        self.assertEqual(self.reader.calls, 0)

    def test_stale_hashes_and_exact_identities_are_rejected_before_reads(self):
        for field, value in (
            ("packet_sha256", "0" * 64),
            ("row_sha256", "0" * 64),
            ("occurrence_sha256", "0" * 64),
            ("catalog_checksum", "0" * 64),
            ("edition_id", 7002),
            ("source_row_id", 2),
            ("source_id", "synthetic-1"),
            ("reference_ordinal", 2),
            ("reference_ordinal", True),
            ("edition_id", 7001.0),
            ("source_row_id", True),
        ):
            with self.subTest(field=field, value=value):
                self.closed(self.join(request=replace(self.request, **{field: value})))
        self.assertEqual(self.reader.calls, 0)

    def test_packet_tampering_with_recomputed_hash_does_not_become_authority(self):
        for field in ("text", "input_text"):
            payload = self.packet.payload()
            payload["source"][field] += "\r\nعَرَبِيّ e\u0301"
            packet = CaseReviewPacket(serialize_packet(payload))
            self.closed(
                self.join(packet=packet, request=replace(self.request, packet_sha256=packet.sha256))
            )
        self.assertEqual(self.reader.calls, 0)

    def test_missing_source_or_reader_does_not_default_to_database(self):
        with patch(
            "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            side_effect=AssertionError("implicit database"),
        ):
            self.closed(self.join(prepared=None), "NOT_CONNECTED")
            self.closed(self.join(reader=None), "NOT_CONNECTED")
        self.assertEqual(self.reader.calls, 0)

    def test_unknown_and_unverified_cases_stay_disconnected(self):
        self.closed(self.join(request=replace(self.request, case_key="unknown")), "NOT_CONNECTED")
        for key in ("intake-2", "history"):
            case = next(c for c in build_investigation().cases if c.case.key == key)
            packet = build_packet(case.case)
            request = replace(
                self.request,
                case_key=key,
                packet_sha256=packet.sha256,
                row_sha256=case.source_sha256,
            )
            self.closed(self.join(request=request, packet=packet), "NOT_CONNECTED")
        self.assertEqual(self.reader.calls, 0)

    def test_prepared_batch_is_not_joined_to_unrelated_catalog(self):
        from apps.editorial_workbench.services import build_prepared_workbench

        key = "batch-synthetic-json-1"
        case = next(c for c in build_investigation().cases if c.case.key == key)
        batch = next(b for b in build_prepared_workbench().batches if b.batch_id == case.batch_id)
        packet = build_packet(case.case, batch)
        self.closed(
            self.join(
                packet=packet,
                request=replace(
                    self.request,
                    case_key=key,
                    packet_sha256=packet.sha256,
                    row_sha256=case.source_sha256,
                ),
            ),
            "NOT_CONNECTED",
        )

    def test_live_topology_metadata_and_checksum_must_match_independent_contract(self):
        for field, value in (
            ("work_title", "مرجع آخر"),
            ("edition_key", "other"),
            ("source_input_sha256", "d" * 64),
            ("publisher", "آخر"),
        ):
            altered = prepare_catalog(
                replace(self.prepared.spec, **{field: value}), self.prepared.records
            )
            self.closed(self.join(reader=Reader(altered, self.headings)))
        altered = prepare_catalog(
            self.prepared.spec,
            self.prepared.records[:-1] + (replace(self.prepared.records[-1], source_page_id=999),),
        )
        self.closed(self.join(reader=Reader(altered, self.headings)))
        self.closed(self.join(prepared=replace(self.prepared, checksum="d" * 64)))

    def test_live_heading_tampering_and_numeric_aliases_close_evidence(self):
        for field, value in (
            ("edition_id", 7001.0),
            ("source_row_id", True),
            ("printed_page", True),
            ("printed_page", 99),
            ("heading_title", "كتاب اصطناعي"),
            ("work_title", "آخر"),
            ("source_archive_sha256", "e" * 64),
        ):
            headings = (replace(self.headings[0], **{field: value}), *self.headings[1:])

            # Raw reader tests strictness beyond SnapshotCatalog constructor.
            class Catalog:
                def lookup(inner, edition, row):
                    return tuple(h for h in headings if h.source_row_id == row)

            reader = Reader(self.prepared, self.headings)
            reader.value = replace(reader.value, evidence=Catalog())
            with self.subTest(field=field):
                self.closed(self.join(reader=reader))

    def test_missing_or_duplicate_exact_catalog_row_withholds_join(self):
        self.closed(self.join(reader=Reader(self.prepared, self.headings[1:])), "NOT_CONNECTED")
        self.closed(self.join(reader=Reader(self.prepared, (*self.headings, self.headings[0]))))

    def test_snapshot_exit_failure_cannot_leak_a_successful_join(self):
        snapshot = self.reader.value
        for at_exit in (False, True):

            class Broken:
                @contextmanager
                def snapshot(inner, edition):
                    if not at_exit:
                        raise CatalogReadError("do not expose private details")
                    yield snapshot
                    raise CatalogReadError("do not expose private details")

            result = self.join(reader=Broken())
            self.closed(result, "NOT_CONNECTED")
            self.assertNotIn("private details", json.dumps(result))

    def test_all_reads_are_inside_one_snapshot_and_inputs_are_immutable(self):
        original = self.reader.value.evidence
        reader = self.reader

        class Evidence:
            def lookup(inner, edition, row):
                self.assertTrue(reader.active)
                return original.lookup(edition, row)

        reader.value = replace(reader.value, evidence=Evidence())
        before = asdict(self.prepared), self.packet.json_bytes
        with ExitStack() as stack:
            for target in (
                "builtins.open",
                "pathlib.Path.open",
                "socket.socket",
                "subprocess.Popen",
                "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            ):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            first, second = self.join(), self.join()
        self.assertEqual(first, second)
        self.assertEqual(before, (asdict(self.prepared), self.packet.json_bytes))
        self.assertEqual(first["status"], "VERIFIED_TECHNICAL")
        self.assertEqual(first["owner_source"], "NOT_CONNECTED")
        self.assertEqual(first["source_acceptance"], "NOT_RUN")
        self.assertIn("U03/U10 OWNER_APPROVAL_PENDING", first["holds"])

    def test_occurrence_hash_is_over_original_utf8_slice(self):
        joined = self.join()["join"]
        provenance = joined["provenance"]
        raw = self.packet.payload()["source"]["input_text"].encode("utf-8")
        occurrence = raw[provenance["occurrence_start"] : provenance["occurrence_end"]]
        self.assertEqual(sha256(occurrence).hexdigest(), self.request.occurrence_sha256)
        self.assertEqual(json.loads(occurrence), joined["original_identity"])
        self.assertEqual(provenance["offset_unit"], "utf8_bytes_end_exclusive")

    def test_opt_in_is_exact_and_invalid_request_is_closed(self):
        for opt in (False, 1, "true"):
            self.closed(self.join(synthetic_fixtures_only=opt))
        for request in (
            None,
            {},
            replace(self.request, case_key=True),
            replace(self.request, row_sha256="A" * 64),
        ):
            self.closed(self.join(request=request))
