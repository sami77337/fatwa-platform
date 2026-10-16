"""Archive safety and historical identity tests; no ORM or database access."""

import hashlib
import io
import json
import os
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.fiqh_import.book622 import (
    ARCHIVE_SHA256,
    EDITION_KEY,
    INPUT_MEMBER,
    MAPPED_CHECKSUM,
    ORIGINAL_MEMBER,
    ORIGINAL_SHA256,
    _read_source_members,
    validate_book622,
)
from tools.fiqh_import.ingest import IngestError, load_manifest
from tools.fiqh_import.owner_r1 import FIQH_BOOK_IDS, INPUT_PINS, INTRODUCTION_IDS

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = Path(os.environ.get(
    "FATWA_622_ARCHIVE", ROOT / "_codex_input/FATWA_622_FIQH_COMPLETE_TOC_11397_20261011.zip"
))


class Book622VerificationTests(unittest.TestCase):
    def zip_bytes(self, members):
        target = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(target, "w") as archive:
                for name, raw in members:
                    archive.writestr(name, raw)
        return target.getvalue()

    def test_truncated_and_altered_archives_fail_before_member_manifest_or_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "synthetic.zip"
            synthetic = self.zip_bytes([(INPUT_MEMBER, b"synthetic"), (ORIGINAL_MEMBER, b"index")])
            for raw in (b"", synthetic[:-20], synthetic + b"altered", b"not a zip"):
                archive.write_bytes(raw)
                before = archive.read_bytes()
                with self.subTest(size=len(raw)), patch(
                    "tools.fiqh_import.book622._read_source_members"
                ) as members, patch("tools.fiqh_import.book622.load_manifest") as manifest:
                    with self.assertRaisesRegex(IngestError, "SHA256"):
                        validate_book622(archive)
                    members.assert_not_called()
                    manifest.assert_not_called()
                    self.assertEqual(archive.read_bytes(), before)

    def test_bounded_archive_read_fails_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "large.zip"
            archive.write_bytes(b"123456789")
            with patch("tools.fiqh_import.book622.MAX_ARCHIVE_BYTES", 8):
                with self.assertRaisesRegex(IngestError, "limit"):
                    validate_book622(archive)

    def test_member_reader_rejects_missing_duplicate_corrupt_or_oversized_members(self):
        # Internal ZIP reader only: these synthetic ZIPs never pass the real archive pin.
        cases = (
            b"not a zip",
            self.zip_bytes([(INPUT_MEMBER, b"a")]),
            self.zip_bytes([(INPUT_MEMBER, b"a"), (INPUT_MEMBER, b"b"), (ORIGINAL_MEMBER, b"c")]),
        )
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaises(IngestError):
                _read_source_members(raw)
        raw = self.zip_bytes([(INPUT_MEMBER, b"12345"), (ORIGINAL_MEMBER, b"a")])
        with patch("tools.fiqh_import.book622.MAX_MEMBER_BYTES", 4):
            with self.assertRaisesRegex(IngestError, "Oversized"):
                _read_source_members(raw)

    def test_member_reader_is_in_memory_and_deterministic(self):
        members = {INPUT_MEMBER: b"synthetic input", ORIGINAL_MEMBER: b"synthetic index"}
        raw = self.zip_bytes(list(members.items()))
        self.assertEqual(_read_source_members(raw), members)
        self.assertEqual(_read_source_members(raw), _read_source_members(raw))

    def test_reviewed_hashes_and_edition_key_cannot_drift_silently(self):
        self.assertEqual(
            ARCHIVE_SHA256,
            "82a797806430635350decdde27d07fe41fb1278838c8173dc4080f9d109957ce",
        )
        self.assertEqual(
            INPUT_PINS["jsonl"],
            "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14",
        )
        self.assertEqual(
            ORIGINAL_SHA256,
            "13edc878f0b81d178c104bc976c4fe0d3970d8a1ef8bae26d6101f22ebbcd1a9",
        )
        self.assertEqual(
            MAPPED_CHECKSUM,
            "b8c69e5f0a7c6b3e7d8b2283bb3e24d89399d646c199c3dc48f19168b8595bf7",
        )
        self.assertEqual(EDITION_KEY, "622-moj-owner-r1-20261011")
        manifest = load_manifest(ROOT / "docs/data-ingest/owner-622-r1-jsonl.manifest.json")
        self.assertEqual(manifest.input_sha256, INPUT_PINS["jsonl"])
        self.assertEqual(
            (manifest.expected_nodes, manifest.expected_roots, manifest.expected_max_depth),
            (11397, 32, 5),
        )

    def test_exact_historical_root_identities_are_frozen_thirty_books_and_two_introductions(self):
        self.assertIsInstance(INTRODUCTION_IDS, frozenset)
        self.assertIsInstance(FIQH_BOOK_IDS, frozenset)
        self.assertEqual(INTRODUCTION_IDS, {"1", "23"})
        self.assertEqual(FIQH_BOOK_IDS, {
            "25", "69", "1321", "1752", "2214", "2618", "3452", "3956",
            "5568", "6833", "7194", "7464", "7877", "8053", "8550", "8898",
            "9241", "9306", "9370", "9474", "9532", "9693", "9873", "10131",
            "10510", "10593", "10649", "10818", "11142", "11289",
        })
        self.assertEqual(len(FIQH_BOOK_IDS | INTRODUCTION_IDS), 32)
        self.assertFalse(FIQH_BOOK_IDS & INTRODUCTION_IDS)


@unittest.skipUnless(ARCHIVE.is_file(), "SOURCE_DATA_MISSING: trusted owner ZIP absent in A4")
class Book622OriginalMappingTests(unittest.TestCase):
    def test_real_mapping_all_original_fields_and_repeat_checksum(self):
        first, report = validate_book622(ARCHIVE)
        second, second_report = validate_book622(ARCHIVE)
        self.assertEqual(first, second)
        self.assertEqual(report, second_report)
        self.assertEqual(first.checksum, MAPPED_CHECKSUM)
        self.assertEqual(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), ARCHIVE_SHA256)
        with zipfile.ZipFile(ARCHIVE) as archive:
            originals = [json.loads(line) for line in archive.read(INPUT_MEMBER).splitlines()]
        fields = {
            "source_id": "lucene_title_key", "source_row_id": "id",
            "parent_source_row_id": "parent_id", "position": "position_among_siblings",
            "depth": "depth", "source_page_id": "source_page_id", "source_part": "source_part",
            "source_page_number": "source_page_number", "title_original": "title",
            "source_entry_number": "source_entry_number",
        }
        self.assertEqual(len(first.records), 11397)
        roots = {
            str(row.source_row_id) for row in first.records if row.parent_source_row_id is None
        }
        self.assertEqual(roots, FIQH_BOOK_IDS | INTRODUCTION_IDS)
        self.assertEqual(max(row.depth for row in first.records), 5)
        for position, (mapped, original) in enumerate(
            zip(first.records, originals, strict=True), 1
        ):
            self.assertEqual(mapped.source_order, position)
            for target, source in fields.items():
                self.assertEqual(getattr(mapped, target), original[source])
        print(json.dumps({
            "fixture": INPUT_MEMBER, "archive_sha256": ARCHIVE_SHA256,
            "input_sha256": report["input_sha256"], "mapped_checksum": first.checksum,
            "mapped_rows": len(first.records), "database_import": "NOT_RUN",
        }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
