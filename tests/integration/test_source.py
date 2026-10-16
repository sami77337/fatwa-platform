"""Optional real owner-source acceptance; never substitutes synthetic source rows."""

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from django.test import TestCase

from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceHeading
from tools.fiqh_import.book622 import ARCHIVE_SHA256, INPUT_MEMBER, validate_book622
from tools.fiqh_import.ingest import IngestError

ARCHIVE = Path(
    os.environ.get(
        "FATWA_622_ARCHIVE", "_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip"
    )
)


class InvalidArchiveTests(unittest.TestCase):
    def test_wrong_archive_pin_fails_before_source_or_database_access(self):
        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / "wrong.zip"
            archive.write_bytes(b"not the owner archive")
            with self.assertRaisesRegex(IngestError, "SHA256"):
                validate_book622(archive)


@unittest.skipUnless(ARCHIVE.is_file(), "Owner source acceptance NOT_RUN: FATWA_622_ARCHIVE absent")
class OriginalSourceMappingTests(unittest.TestCase):
    def test_complete_s1_to_s0_mapping_and_deterministic_checksum(self):
        first, report = validate_book622(ARCHIVE)
        second, _ = validate_book622(ARCHIVE)
        self.assertEqual(first.checksum, second.checksum)
        self.assertEqual(len(first.records), 11397)
        self.assertEqual(sum(row.parent_source_row_id is None for row in first.records), 32)
        self.assertEqual(max(row.depth for row in first.records), 5)
        self.assertEqual(report["exact_original_id_title_matches"], 11397)
        self.assertEqual(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), ARCHIVE_SHA256)
        with zipfile.ZipFile(ARCHIVE) as archive:
            originals = [json.loads(line) for line in archive.read(INPUT_MEMBER).splitlines()]
        for position, (mapped, original) in enumerate(
            zip(first.records, originals, strict=True), 1
        ):
            self.assertEqual(mapped.source_order, position)
            self.assertEqual(mapped.source_id, original["lucene_title_key"])
            self.assertEqual(mapped.source_row_id, original["id"])
            self.assertEqual(mapped.parent_source_row_id, original["parent_id"])
            self.assertEqual(mapped.position, original["position_among_siblings"])
            self.assertEqual(mapped.depth, original["depth"])
            self.assertEqual(mapped.title_original, original["title"])
            self.assertEqual(mapped.source_page_id, original["source_page_id"])
            self.assertEqual(mapped.source_part, original["source_part"])
            self.assertEqual(mapped.source_page_number, original["source_page_number"])
            self.assertEqual(mapped.source_entry_number, original["source_entry_number"])


@unittest.skipUnless(
    ARCHIVE.is_file(), "Real PostgreSQL source import NOT_RUN: FATWA_622_ARCHIVE absent"
)
class OriginalSourcePersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.prepared, _ = validate_book622(ARCHIVE)
        preview = ingest_catalog(cls.prepared.spec, cls.prepared.records)
        cls.result = ingest_catalog(
            cls.prepared.spec,
            cls.prepared.records,
            dry_run=False,
            expected_checksum=preview.checksum,
        )

    def test_every_persisted_field_and_idempotent_rerun(self):
        rows = (
            ReferenceHeading.objects.filter(edition_id=self.result.edition_id)
            .order_by("source_order")
            .values(
                "source_id",
                "source_row_id",
                "parent__source_row_id",
                "source_order",
                "position",
                "depth",
                "source_page_id",
                "source_part",
                "source_page_number",
                "source_entry_number",
                "title_original",
            )
        )
        self.assertEqual(len(rows), 11397)
        for row, expected in zip(rows, self.prepared.records, strict=True):
            for field, value in row.items():
                target = "parent_source_row_id" if field == "parent__source_row_id" else field
                self.assertEqual(value, getattr(expected, target))
        rerun = ingest_catalog(
            self.prepared.spec,
            self.prepared.records,
            dry_run=False,
            expected_checksum=self.prepared.checksum,
        )
        self.assertTrue(rerun.unchanged)
        self.assertEqual(rerun.edition_id, self.result.edition_id)
        self.assertEqual(ReferenceHeading.objects.count(), 11397)
