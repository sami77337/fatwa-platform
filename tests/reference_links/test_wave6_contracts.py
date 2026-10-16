"""Synthetic E3 regressions; safe under C6/D6's unreachable PostgreSQL port."""

import json
import unittest
from dataclasses import asdict, replace
from unittest.mock import Mock, patch

from apps.reference_links.bridge import (
    BridgeConfig, EditionMap, HeadingMap, resolve_prepared_pointers,
)
from apps.reference_links.demo import fixtures
from apps.reference_links.resolution import CatalogReadError, Outcome, SnapshotCatalog, resolve, resolve_intake


def envelope(links):
    return json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [
        {"external_id": "unseen", "reference_links": links},
    ]}, ensure_ascii=True).encode()


class Wave6Contracts(unittest.TestCase):
    def setUp(self):
        self.config, self.heading = fixtures()
        self.pointer = {"source_id": "source-X", "heading_id": "heading-Y"}
        self.catalog = SnapshotCatalog((self.heading,))

    def links(self, links, catalog=None):
        return resolve_prepared_pointers(
            envelope(links), self.config, catalog or self.catalog,
        )[0].reference_links

    def test_malformed_object_does_not_discard_valid_sibling(self):
        malformed = {"source_id": 41, "heading_id": "heading-Y"}
        result = self.links([malformed, self.pointer])
        self.assertEqual(result[0].reasons, ("invalid_pointer",))
        self.assertEqual(dict(result[0].original_pointer), malformed)
        self.assertIsNone(result[0].citation)
        self.assertEqual(result[1].status, Outcome.VERIFIED)

    def test_non_object_pointer_is_retained_as_invalid(self):
        for value in (None, 41, "source-X", ["source-X"]):
            with self.subTest(value=value):
                result = self.links([value, self.pointer])
                self.assertEqual(result[0].reasons, ("invalid_pointer",))
                self.assertEqual(result[0].original_pointer, (("$invalid_pointer", value),))
                self.assertEqual(result[1].status, Outcome.VERIFIED)

    def test_duplicate_invalid_values_and_reordered_exact_pointers(self):
        first, second, valid = self.links([
            {"source_id": [41]}, {"source_id": [41]}, self.pointer,
        ])
        self.assertEqual(first.reasons, ("invalid_pointer",))
        self.assertEqual(second.reasons, ("invalid_pointer",))
        self.assertEqual(valid.status, Outcome.VERIFIED)
        reordered = dict(reversed(tuple(self.pointer.items())))
        self.assertTrue(all(r.reasons == ("duplicate_pointer",)
                            for r in self.links([self.pointer, reordered])))

    def test_missing_and_nonexact_c1_pointer_never_looks_up(self):
        catalog = Mock()
        for pointer in ({}, {"source_id": "source-X"},
                        {"source_id": "source-X", "heading_id": " heading-Y"},
                        {"source_id": "source-X", "heading_id": "heading-\u064a"},
                        {"source_id": "source-X", "heading_id": "heading-\u0649"}):
            self.assertEqual(self.links([pointer], catalog)[0].status, Outcome.UNVERIFIED)
        catalog.lookup.assert_not_called()

    def test_all_six_c2_fields_required_and_retained_exactly(self):
        pointer = {**asdict(self.config.edition.identity), "source_id": "row-Z"}
        result = self.links([pointer])[0]
        self.assertEqual(result.status, Outcome.VERIFIED)
        self.assertEqual(result.original_pointer, tuple(pointer.items()))
        for key in pointer:
            with self.subTest(key=key):
                incomplete = {k: v for k, v in pointer.items() if k != key}
                self.assertEqual(self.links([incomplete])[0].status, Outcome.UNVERIFIED)

    def test_input_byte_limit_before_decoding_on_both_entrypoints(self):
        # Valid envelope just over the shared maximum, below the previous 2 MB limit.
        raw = envelope([]) + b" " * 1_000_000
        for run in (lambda: resolve_prepared_pointers(raw, self.config, self.catalog),
                    lambda: resolve_intake(raw, self.catalog)):
            with self.assertRaises(ValueError):
                run()

    def test_row_and_reference_limits(self):
        for raw in (envelope([self.pointer] * 101), json.dumps({
            "schema": "fatwa.prepared-intake.v1", "items": [
                {"external_id": str(i)} for i in range(1001)
            ],
        }).encode()):
            with self.assertRaises(ValueError):
                resolve_prepared_pointers(raw, self.config, self.catalog)

    def test_malformed_adapter_evidence_is_unverified(self):
        for values in ({"path": None}, {"path": list(self.heading.path)},
                       {"source_input_sha256": None}):
            with self.subTest(values=values):
                catalog = SnapshotCatalog((replace(self.heading, **values),))
                result = resolve({"edition_id": 41, "source_row_id": 73}, catalog)
                self.assertEqual(result.outcome, Outcome.UNVERIFIED)
                self.assertIsNone(result.evidence)

    def test_explicit_numeric_maps_do_not_cast_opaque_ids(self):
        for value in ("41", True, 0, 2**63):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EditionMap(self.config.edition.identity, value)
        self.assertEqual(self.links([{"source_id": "41", "heading_id": "73"}])[0].status,
                         Outcome.UNVERIFIED)

    def test_catalog_failure_suppresses_evidence_and_citation(self):
        catalog = Mock()
        catalog.lookup.side_effect = CatalogReadError("synthetic failure")
        result = self.links([self.pointer], catalog)[0]
        self.assertEqual(result.reasons, ("catalog_unavailable",))
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.citation)

    def test_snapshot_edition_metadata_when_supplied_must_match(self):
        for key, value in (("edition_key", "different"), ("source_archive_sha256", "c" * 64)):
            with self.subTest(key=key):
                catalog = SnapshotCatalog((replace(self.heading, **{key: value}),))
                result = self.links([self.pointer], catalog)[0]
                self.assertEqual(result.reasons, ("catalog_source_pin_mismatch",))
                self.assertIsNone(result.evidence)
                self.assertIsNone(result.citation)

    def test_matching_snapshot_edition_metadata_retains_every_pin(self):
        identity = self.config.edition.identity
        heading = replace(self.heading, edition_key=identity.edition_key,
                          source_archive_sha256=identity.source_archive_sha256)
        result = self.links([self.pointer], SnapshotCatalog((heading,)))[0]
        self.assertEqual(result.status, Outcome.VERIFIED)
        self.assertEqual(result.evidence, heading)

    def test_bounded_distinct_batch_indexes_mapping_once(self):
        # Count complete map iterations, independent of wall-clock scheduling.
        mappings = tuple(HeadingMap("s", f"h{i}", f"c{i}", i + 1) for i in range(2000))
        config = BridgeConfig(self.config.edition, mappings)
        rows = tuple(replace(self.heading, source_row_id=i + 1) for i in range(100))
        catalog = Mock(wraps=SnapshotCatalog(rows))
        raw = json.dumps({"schema": "fatwa.prepared-intake.v1", "items": [
            {"external_id": f"r{r}", "reference_links": [
                {"source_id": "s", "heading_id": f"h{i}"} for i in range(100)
            ]} for r in range(10)
        ]}).encode()
        iterations = []
        original = HeadingMap.__getattribute__

        def count(mapping, key):
            if key == "c1_source_id":
                iterations.append(1)
            return original(mapping, key)

        with patch.object(HeadingMap, "__getattribute__", count):
            results = resolve_prepared_pointers(raw, config, catalog)
        self.assertEqual(len(iterations), len(mappings))
        self.assertEqual(catalog.lookup.call_count, 1000)
        self.assertTrue(all(p.status == Outcome.VERIFIED for r in results for p in r.reference_links))
