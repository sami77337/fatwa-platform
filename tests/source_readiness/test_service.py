import copy
import io
import json
import unittest
import zipfile
from hashlib import sha256

from apps.reference.records import CatalogSpec, HeadingRecord, prepare_catalog
from apps.source_readiness.service import preflight
from tests.source_readiness.fixtures import bundle, encode


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.snapshot, self.raw, self.archive = bundle()

    def run_check(self, **kwargs):
        args = dict(
            manifest=encode(self.manifest),
            snapshot=encode(self.snapshot),
            input_bytes=self.raw,
            archive_bytes=self.archive,
        )
        args.update(kwargs)
        return preflight(**args).as_dict()

    def test_generated_exact_bytes_pass_only_synthetic_readiness(self):
        before = copy.deepcopy(self.snapshot)
        report = self.run_check()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["owner_acceptance"], "NOT_RUN")
        self.assertEqual(report["dataset_id"], self.manifest["dataset_id"])
        self.assertEqual(report["observed_sha256"]["input"], sha256(self.raw).hexdigest())
        self.assertEqual(self.snapshot, before)
        self.assertEqual(report, self.run_check())

    def test_metadata_only_never_accepts_raw_evidence(self):
        report = self.run_check(input_bytes=None, archive_bytes=None)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"]["input_sha256"]["status"], "NOT_RUN")
        self.assertEqual(report["checks"]["catalog_metadata"]["status"], "PASS")

    def test_no_evidence_is_not_run_and_owner_mode_never_checks_raw_bytes(self):
        self.assertEqual(preflight(None).status, "NOT_RUN")
        self.manifest["source_kind"] = "owner_supplied"
        report = self.run_check(input_bytes=b"not inspected", archive_bytes=b"not inspected")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["owner_acceptance"], "NOT_RUN")
        self.assertEqual(report["observed_sha256"], {})

    def test_every_identity_and_edition_assertion_is_exact(self):
        for field in self.snapshot["spec"]:
            changed = copy.deepcopy(self.snapshot)
            value = changed["spec"][field]
            changed["spec"][field] = value + 1 if type(value) is int else value + "x"
            with self.subTest(field=field):
                self.assertEqual(self.run_check(snapshot=encode(changed))["status"], "FAIL")
        self.snapshot["edition_id"] = True
        self.assertEqual(self.run_check()["status"], "FAIL")

    def test_tampered_input_and_archive_fail_independently(self):
        for key in ("input_bytes", "archive_bytes"):
            with self.subTest(key=key):
                self.assertEqual(self.run_check(**{key: b"changed"})["status"], "FAIL")

    def test_stale_catalog_checksum_and_exact_original_title(self):
        self.snapshot["records"][0]["title_original"] = "كتاب اصطناعي"
        report = self.run_check()
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("stale_catalog_checksum", report["checks"]["catalog_integrity"]["reasons"])

    def test_hierarchy_and_printed_location_are_strict(self):
        for key, value in (
            ("parent_source_row_id", 999),
            ("parent_source_row_id", 2),
            ("depth", 1),
            ("source_row_id", 1),
            ("source_id", "synthetic:1"),
            ("source_order", 1),
            ("source_page_number", True),
            ("source_part", ""),
            ("source_page_id", None),
            ("position", 0),
        ):
            changed = copy.deepcopy(self.snapshot)
            changed["records"][1][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(self.run_check(snapshot=encode(changed))["status"], "FAIL")

    def test_raw_rows_cannot_be_replaced_with_matching_hash_only(self):
        raw = json.loads(self.raw)
        raw["records"][1]["source_page_number"] = 999
        self.raw = encode(raw)
        self.manifest["spec"]["source_input_sha256"] = sha256(self.raw).hexdigest()
        self.snapshot["spec"]["source_input_sha256"] = sha256(self.raw).hexdigest()
        self.assertEqual(self.run_check()["checks"]["source_rows"]["status"], "FAIL")

    def test_invalid_manifest_types_unknown_fields_duplicates_and_nonfinite_fail(self):
        for raw in (
            b"{}",
            b"[]",
            b"null",
            b'{"schema":1,"schema":2}',
            b'{"x": NaN}',
            b"\xff",
            b"[" * 2000,
        ):
            with self.subTest(raw=raw[:50]):
                self.assertEqual(self.run_check(manifest=raw)["status"], "FAIL")
        for key, value in (
            ("edition_id", True),
            ("source_kind", "real"),
            ("unexpected", "field"),
            ("catalog_checksum", "A" * 64),
        ):
            changed = {**self.manifest, key: value}
            self.assertEqual(self.run_check(manifest=encode(changed))["status"], "FAIL")

    def test_missing_snapshot_blocks_and_malformed_snapshot_fails(self):
        self.assertEqual(self.run_check(snapshot=None)["status"], "BLOCKED")
        for raw in (b"null", b"{}", b"\xff"):
            self.assertEqual(self.run_check(snapshot=raw)["status"], "FAIL")

    def test_pinned_owner_metadata_never_invents_local_edition_or_opens_archive(self):
        from apps.source_readiness.pins import pinned_owner_manifest

        manifest = json.loads(pinned_owner_manifest())
        self.assertIsNone(manifest["edition_id"])
        self.assertEqual(manifest["spec"]["source_namespace"], "shamela")
        report = preflight(encode(manifest)).as_dict()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["owner_acceptance"], "NOT_RUN")
        self.assertEqual(report["observed_sha256"], {})
        self.assertEqual(
            report["expected_sha256"]["input"],
            "37544f6122ef72fb6bd908556ffb41821b235be28bcbd1413752042dbac01d14",
        )

    def repin(self):
        for spec in (self.manifest["spec"], self.snapshot["spec"]):
            spec["source_input_sha256"] = sha256(self.raw).hexdigest()
            spec["source_archive_sha256"] = sha256(self.archive).hexdigest()
        prepared = prepare_catalog(
            CatalogSpec(**self.snapshot["spec"]),
            [HeadingRecord(**row) for row in self.snapshot["records"]],
        )
        self.manifest["catalog_checksum"] = prepared.checksum

    def test_hashed_zip_requires_exact_member_name_and_bytes(self):
        for entries in (
            [("wrong-name.json", self.raw)],
            [(self.manifest["spec"]["input_name"], b"wrong")],
            [("../escape.json", self.raw)],
            [],
            [(self.manifest["spec"]["input_name"], self.raw), ("extra", b"extra")],
        ):
            with self.subTest(entries=[name for name, _ in entries]):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w") as archive:
                    for name, payload in entries:
                        archive.writestr(name, payload)
                self.archive = stream.getvalue()
                self.repin()
                report = self.run_check()
                self.assertEqual(report["checks"]["archive_sha256"]["status"], "PASS")
                self.assertEqual(report["checks"]["archive_member"]["status"], "FAIL")

    def test_raw_identity_and_rows_fail_even_with_matching_manifest_hash(self):
        for key, value in (
            ("source_book_id", "623"),
            ("edition_key", "other"),
            ("work_title", "مرجع آخر"),
            ("publisher", None),
        ):
            raw = json.loads(bundle()[2])
            raw["identity"][key] = value
            self.raw = encode(raw)
            self.repin()
            with self.subTest(key=key):
                self.assertEqual(self.run_check()["checks"]["source_rows"]["status"], "FAIL")

    def test_raw_hierarchy_and_printed_evidence_require_valid_exact_fields(self):
        for key, value in (
            ("parent_source_row_id", 2),
            ("source_row_id", True),
            ("source_page_number", None),
            ("source_part", ""),
            ("source_page_id", 0),
            ("title_original", "\ud800"),
            ("depth", 9),
            ("source_entry_number", False),
        ):
            raw = json.loads(bundle()[2])
            raw["records"][1][key] = value
            self.raw = json.dumps(raw).encode()
            self.repin()
            with self.subTest(key=key):
                report = self.run_check()
                self.assertEqual(report["status"], "FAIL")
                self.assertNotEqual(report["checks"]["printed_location"]["status"], "PASS")

    def test_oversize_and_malformed_bytes_fail_closed(self):
        for key in ("manifest", "snapshot", "input_bytes", "archive_bytes"):
            with self.subTest(key=key):
                self.assertEqual(
                    self.run_check(**{key: b"x" * (16 * 1024 * 1024 + 1)})["status"], "FAIL"
                )
        for value in (b"null", b"[]", b"{}", b"[" * 2000, b"\xff"):
            self.raw = value
            self.repin()
            self.assertEqual(self.run_check()["status"], "FAIL")

    def test_false_synthetic_claim_cannot_open_inherited_owner_identity(self):
        self.manifest["spec"]["source_namespace"] = "shamela"
        self.assertEqual(self.run_check()["checks"]["manifest"]["status"], "FAIL")

    def test_shuffled_snapshot_records_preserve_exact_source_order(self):
        self.snapshot["records"].reverse()
        self.assertEqual(self.run_check()["status"], "PASS")

    def test_one_source_page_id_cannot_assert_two_printed_locations(self):
        raw = json.loads(self.raw)
        raw["records"][1]["source_page_id"] = 101
        self.snapshot["records"][1]["source_page_id"] = 101
        self.raw = encode(raw)
        self.repin()
        report = self.run_check()
        self.assertEqual(report["checks"]["printed_location"]["status"], "FAIL")

    def test_corrupt_compressed_archive_returns_failure_not_exception(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.manifest["spec"]["input_name"], self.raw)
        damaged = bytearray(stream.getvalue())
        offset = 30 + len(self.manifest["spec"]["input_name"].encode())
        damaged[offset] = 0xFF  # Invalid DEFLATE block type, with a newly pinned hash.
        self.archive = bytes(damaged)
        self.repin()
        self.assertEqual(self.run_check()["checks"]["archive_member"]["status"], "FAIL")

    def test_unsupported_zip_codecs_fail_before_decompression(self):
        for codec in (zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2):
            with self.subTest(codec=codec):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w", compression=codec) as archive:
                    archive.writestr(self.manifest["spec"]["input_name"], self.raw)
                self.archive = stream.getvalue()
                self.repin()
                self.assertEqual(self.run_check()["checks"]["archive_member"]["status"], "FAIL")
                if codec == zipfile.ZIP_LZMA:
                    damaged = bytearray(self.archive)
                    offset = 30 + len(self.manifest["spec"]["input_name"].encode()) + 9
                    damaged[offset] ^= 0xFF
                    self.archive = bytes(damaged)
                    self.repin()
                    self.assertEqual(self.run_check()["checks"]["archive_member"]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
