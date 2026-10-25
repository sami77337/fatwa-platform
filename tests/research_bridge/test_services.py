"""Exact synthetic identity gates; no database or source imports."""

import json
from dataclasses import asdict, replace
from unittest import TestCase
from unittest.mock import Mock

from apps.reference_links.resolution import CatalogReadError, Heading, SnapshotCatalog
from apps.reference_triage.services import build_investigation
from apps.research_bridge.services import bridge_reference


def verified_fixture():
    return next(
        ref
        for row in build_investigation().cases
        for ref in row.references
        if ref.raw_status == "verified" and json.loads(ref.evidence).get("edition_key")
    )


def heading_for(ref):
    data = json.loads(ref.evidence)
    data["path"] = tuple(data["path"])
    return Heading(**data)


class BridgeServiceTests(TestCase):
    def setUp(self):
        self.ref = verified_fixture()
        self.heading = heading_for(self.ref)
        self.catalog = SnapshotCatalog((self.heading,))

    def assert_closed(self, result):
        self.assertEqual(result.status, "unverified")
        self.assertIsNone(result.catalog_url)
        self.assertIsNone(result.evidence)
        self.assertTrue(result.reason)
        self.assertTrue(result.recovery)

    def test_exact_verified_source_returns_original_metadata_and_edition_scoped_link(self):
        before = asdict(self.ref)
        result = bridge_reference(self.ref, self.catalog)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.evidence, self.heading)
        self.assertEqual(result.catalog_url, "/fiqh/nodes/1?edition=7001")
        self.assertEqual(asdict(self.ref), before)

    def test_every_existing_unverified_occurrence_stays_closed_without_lookup(self):
        catalog = Mock()
        for row in build_investigation().cases:
            for ref in row.references:
                if ref.raw_status != "verified":
                    self.assert_closed(bridge_reference(ref, catalog))
        catalog.lookup.assert_not_called()

    def test_status_contract_or_missing_evidence_cannot_be_promoted(self):
        catalog = Mock()
        for change in (
            {"status": "unresolved"},
            {"raw_status": "unverified"},
            {"contract_status": "UNVERIFIED"},
            {"evidence": "null"},
            {"verified_identity": "{}"},
            {"evidence": "[]"},
            {"verified_identity": "invalid"},
            {"reasons": ("contradiction",)},
        ):
            with self.subTest(change=change):
                self.assert_closed(bridge_reference(replace(self.ref, **change), catalog))
        catalog.lookup.assert_not_called()

    def test_each_required_identity_field_is_exact_and_present_before_lookup(self):
        identity = json.loads(self.ref.verified_identity)
        catalog = Mock()
        for key in (
            "source_namespace",
            "source_book_id",
            "edition_key",
            "source_archive_sha256",
            "source_input_sha256",
            "edition_id",
            "source_row_id",
        ):
            for value in (None, "", "other", True):
                changed = {**identity, key: value}
                with self.subTest(key=key, value=value):
                    self.assert_closed(
                        bridge_reference(
                            replace(self.ref, verified_identity=json.dumps(changed)), catalog
                        )
                    )
            changed = {k: v for k, v in identity.items() if k != key}
            self.assert_closed(
                bridge_reference(replace(self.ref, verified_identity=json.dumps(changed)), catalog)
            )
        catalog.lookup.assert_not_called()

    def test_partial_legacy_evidence_is_never_completed_from_catalog(self):
        for key in ("edition_key", "source_archive_sha256"):
            evidence = json.loads(self.ref.evidence)
            evidence[key] = None
            catalog = Mock()
            self.assert_closed(
                bridge_reference(replace(self.ref, evidence=json.dumps(evidence)), catalog)
            )
            catalog.lookup.assert_not_called()

    def test_prepared_verified_label_without_full_evidence_never_queries_catalog(self):
        catalog = Mock()
        incomplete = [
            ref
            for row in build_investigation().cases
            for ref in row.references
            if ref.raw_status == "verified" and json.loads(ref.evidence) is None
        ]
        self.assertTrue(incomplete)
        for ref in incomplete:
            self.assert_closed(bridge_reference(ref, catalog))
        catalog.lookup.assert_not_called()

    def test_nonroot_heading_keeps_exact_parent_hierarchy_without_normalization(self):
        title = "  بَابٌ  اصطناعي <تجربة> e\u0301  "
        expected = replace(
            self.heading,
            heading_title=title,
            path=(self.heading.heading_title, title),
            source_row_id=2,
            printed_page=8,
        )
        identity = json.loads(self.ref.verified_identity)
        identity["source_row_id"] = 2
        reference = replace(
            self.ref, verified_identity=json.dumps(identity), evidence=json.dumps(asdict(expected))
        )
        result = bridge_reference(reference, SnapshotCatalog((expected,)))
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.evidence.path, expected.path)
        self.assertEqual(result.evidence.heading_title, title)
        self.assertEqual(result.catalog_url, "/fiqh/nodes/2?edition=7001")

    def test_each_catalog_identity_or_metadata_change_hides_evidence_and_link(self):
        for change in (
            {"edition_id": 7002},
            {"source_row_id": 2},
            {"source_namespace": "other"},
            {"source_book_id": "623"},
            {"edition_key": None},
            {"edition_key": "other"},
            {"source_archive_sha256": None},
            {"source_archive_sha256": "c" * 64},
            {"source_input_sha256": "c" * 64},
            {"work_title": "آخر"},
            {"heading_title": "آخر"},
            {"path": ("أصل آخر", self.heading.heading_title)},
            {"printed_part": "الثاني"},
            {"printed_page": 8},
            {"printed_page": None},
        ):
            with self.subTest(change=change):
                catalog = Mock()
                catalog.lookup.return_value = (replace(self.heading, **change),)
                self.assert_closed(bridge_reference(self.ref, catalog))

    def test_missing_ambiguous_and_unavailable_catalog_fail_closed(self):
        for catalog in (SnapshotCatalog(()), SnapshotCatalog((self.heading, self.heading))):
            self.assert_closed(bridge_reference(self.ref, catalog))
        catalog = Mock()
        catalog.lookup.side_effect = CatalogReadError("private connection detail")
        result = bridge_reference(self.ref, catalog)
        self.assert_closed(result)
        self.assertEqual(result.reason, "catalog_unavailable")
        self.assertNotIn("private", result.recovery)

    def test_malformed_expected_path_fails_before_lookup(self):
        for path in ([], ["wrong"], "text", [None], ["root"] * 6):
            expected = json.loads(self.ref.evidence)
            expected["path"] = path
            catalog = Mock()
            self.assert_closed(
                bridge_reference(replace(self.ref, evidence=json.dumps(expected)), catalog)
            )
            catalog.lookup.assert_not_called()
