import copy
import json
import unittest
from hashlib import sha256
from unittest.mock import patch

from apps.fast8_source_preflight.service import verify_receipt
from apps.source_readiness.service import MAX_MANIFEST_BYTES
from tests.fast8_source_preflight.fixtures import AS_OF, encode, fixture, receipt_data


class ReceiptTests(unittest.TestCase):
    def check_data(self, data, status="FAIL", **kwargs):
        raw = encode(data)
        report = verify_receipt(
            raw, expected_sha256=sha256(raw).hexdigest(), as_of=kwargs.pop("as_of", AS_OF), **kwargs
        )
        self.assertEqual(report.status, status, report.as_dict())
        return report

    def test_pinned_receipt_is_deterministic_and_never_source_acceptance(self):
        raw, digest = fixture()
        with patch("builtins.open", side_effect=AssertionError("no file access")):
            first = verify_receipt(raw, expected_sha256=digest, as_of=AS_OF)
            second = verify_receipt(raw, expected_sha256=digest, as_of=AS_OF)
        self.assertEqual(first, second)
        self.assertEqual(first.status, "RECEIPT_VERIFIED")
        payload = first.as_dict()
        self.assertEqual(payload["receipt_sha256"], digest)
        self.assertEqual(payload["source_count"], 1)
        for key in ("source_bytes", "owner_archives"):
            self.assertEqual(payload[key], "NOT_SUPPLIED")
        for key in (
            "archive_verification",
            "heading_count_verification",
            "ordering_verification",
            "owner_acceptance",
        ):
            self.assertEqual(payload[key], "NOT_RUN")
        self.assertEqual(payload["catalog_connection"], "NOT_CONNECTED")
        self.assertEqual(payload["gates"]["B"], "NOT_PASSED")
        self.assertEqual(payload["gates"]["U03_U10"], "OWNER_APPROVAL_PENDING")

    def test_absent_receipt_does_not_infer_owner_evidence(self):
        report = verify_receipt(None)
        self.assertEqual(report.status, "NOT_RUN")
        self.assertEqual(report.as_dict()["owner_archives"], "NOT_SUPPLIED")

    def test_external_pin_and_time_are_required(self):
        raw, digest = fixture()
        for kwargs in ({}, {"as_of": AS_OF}, {"expected_sha256": digest}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(verify_receipt(raw, **kwargs).status, "BLOCKED")

    def test_raw_byte_tampering_including_arabic_crlf_and_timestamp_fails(self):
        raw, digest = fixture()
        for altered in (
            raw.replace(b"\r\n", b"\n"),
            raw + b" ",
            raw.replace("مرجع".encode(), "مَرجع".encode()),
            raw.replace(b"2026-10-26T00:00:00Z", b"2026-10-26T01:00:00Z"),
            raw.replace(b'"archive_size_bytes": ', b'"archive_size_bytes": 1'),
        ):
            with self.subTest(altered=sha256(altered).hexdigest()):
                report = verify_receipt(altered, expected_sha256=digest, as_of=AS_OF)
                self.assertEqual(report.reasons, ("receipt_sha256_mismatch",))

    def test_invalid_trust_anchors(self):
        raw, digest = fixture()
        for pin in (True, [], "a" * 63, digest.upper()):
            self.assertEqual(verify_receipt(raw, expected_sha256=pin, as_of=AS_OF).status, "FAIL")
        self.assertEqual(
            verify_receipt(
                raw, expected_sha256=digest, as_of=AS_OF, expected_revision="main"
            ).status,
            "FAIL",
        )

    def test_expiry_is_exclusive_issue_time_is_inclusive(self):
        data = receipt_data()
        self.check_data(data, "RECEIPT_VERIFIED", as_of=data["issued_at"])
        for time in (data["expires_at"], "2026-10-25T23:59:59Z", "2026-10-28T00:00:00Z"):
            self.check_data(data, as_of=time)

    def test_bad_timestamps_and_excessive_validity(self):
        for time in (
            "2026-10-26",
            "2026-10-26T00:00:00+00:00",
            "2026-02-30T00:00:00Z",
            "2026-10-26T00:00:00.000Z",
            True,
            None,
        ):
            with self.subTest(time=time):
                data = receipt_data()
                data["issued_at"] = time
                self.check_data(data)
        for expiry in ("2026-10-26T00:00:00Z", "2026-11-03T00:00:00Z"):
            data = receipt_data()
            data["expires_at"] = expiry
            self.check_data(data)

    def test_stale_revision_is_rejected_even_with_new_digest(self):
        data = receipt_data()
        data["base_sha"] = "a" * 40
        self.check_data(data)

    def test_strict_json_rejects_duplicate_keys_nonfinite_and_bad_shapes(self):
        raw, _ = fixture()
        cases = [
            b"[]",
            b"null",
            b"true",
            b"\xff",
            b"{",
            b"\xef\xbb\xbf{}",
            b'{"schema":NaN}',
            b'{"schema":Infinity}',
            b'{"schema":1e999}',
            b"[" * 1500 + b"]" * 1500,
            raw.replace(b'"schema":', b'"schema":"duplicate","schema":', 1),
            raw.replace(b'"archive_id":', b'"archive_id":"duplicate","archive_id":', 1),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate[:40]):
                report = verify_receipt(
                    candidate, expected_sha256=sha256(candidate).hexdigest(), as_of=AS_OF
                )
                self.assertEqual(report.status, "FAIL")

    def test_size_and_source_count_limits(self):
        for candidate in ("text", bytearray(b"{}"), b" " * (MAX_MANIFEST_BYTES + 1)):
            self.assertEqual(verify_receipt(candidate).status, "FAIL")
        for sources in ([], {}, [None], [receipt_data()["sources"][0]] * 33):
            data = receipt_data()
            data["sources"] = sources
            self.check_data(data)

    def test_strict_fields_and_explicit_fabrication(self):
        for path, field, value in (
            ((), "extra", True),
            ((), "fabrication", "owner_supplied"),
            ((), "receipt_id", "owner-receipt"),
            (("sources", 0), "path", "private.zip"),
            (("sources", 0), "archive_id", "../synthetic-id"),
            (("sources", 0, "manifest"), "source_kind", "owner_supplied"),
            (("sources", 0, "manifest"), "edition_id", True),
            (("sources", 0, "manifest", "spec"), "source_archive_sha256", "A" * 64),
            (("sources", 0, "manifest", "spec"), "expected_rows", True),
            (("sources", 0, "manifest", "spec"), "expected_roots", 3),
        ):
            data = receipt_data()
            target = data
            for part in path:
                target = target[part]
            target[field] = value
            with self.subTest(path=path, field=field):
                self.check_data(data)

    def test_declared_sizes_are_positive_bounded_integers(self):
        for field in ("archive_size_bytes", "input_size_bytes"):
            for value in (True, 0, -1, 1.5, "123", None, 2**63):
                data = receipt_data()
                data["sources"][0][field] = value
                self.check_data(data)

    def test_path_traversal_devices_and_ambiguous_names_are_rejected(self):
        for name in (
            "../synthetic-x.zip",
            "..\\synthetic-x.zip",
            "/synthetic-x.zip",
            "C:\\synthetic-x.zip",
            "C:synthetic-x.zip",
            "\\\\host\\synthetic-x.zip",
            "synthetic-x.zip:stream",
            "synthetic-x.zip.",
            "synthetic-x.zip ",
            "synthetic-%2e%2e.zip",
            "synthetic-x/../a.zip",
            "CON.zip",
            "NUL",
            "synthetic-\u202ex.zip",
            "synthetic-\x00.zip",
            "synthetic-\ud800.zip",
            "synthetic-*.zip",
            "synthetic-?.zip",
            ".",
            "..",
        ):
            for field in ("archive_name", "input_name"):
                data = receipt_data()
                entry = data["sources"][0]
                target = entry if field == "archive_name" else entry["manifest"]["spec"]
                target[field] = name
                # Escaped surrogate input is legal JSON but invalid receipt text.
                raw = json.dumps(data, ensure_ascii=True).encode()
                with self.subTest(name=name, field=field):
                    self.assertEqual(
                        verify_receipt(
                            raw, expected_sha256=sha256(raw).hexdigest(), as_of=AS_OF
                        ).status,
                        "FAIL",
                    )

    def test_duplicate_source_identities_are_rejected(self):
        base = receipt_data()
        original = base["sources"][0]
        unique = copy.deepcopy(original)
        unique["archive_id"] = "synthetic-second"
        unique["archive_name"] = "synthetic-second.zip"
        unique["manifest"]["dataset_id"] = "synthetic-second"
        unique["manifest"]["edition_id"] = 7002
        unique["manifest"]["spec"]["edition_key"] = "synthetic-second"
        unique["manifest"]["spec"]["source_archive_sha256"] = "a" * 64
        valid = receipt_data()
        valid["sources"].append(copy.deepcopy(unique))
        self.assertEqual(self.check_data(valid, "RECEIPT_VERIFIED").source_count, 2)
        for path in (
            ("archive_id",),
            ("archive_name",),
            ("manifest", "dataset_id"),
            ("manifest", "edition_id"),
            ("manifest", "spec", "edition_key"),
            ("manifest", "spec", "source_archive_sha256"),
        ):
            entry = copy.deepcopy(unique)
            target, source = entry, original
            for part in path[:-1]:
                target, source = target[part], source[part]
            target[path[-1]] = source[path[-1]]
            data = receipt_data()
            data["sources"].append(entry)
            self.check_data(data)
        for left, right in (
            ("synthetic-A.zip", "synthetic-a.zip"),
            ("synthetic-é.zip", "synthetic-e\u0301.zip"),
        ):
            data = receipt_data()
            data["sources"][0]["archive_name"] = left
            entry = copy.deepcopy(unique)
            entry["archive_name"] = right
            data["sources"].append(entry)
            self.check_data(data)

    def test_ordering_claim_must_bind_input_digest_and_count(self):
        for field, value in (
            ("kind", "sorted_titles"),
            ("heading_count", True),
            ("heading_count", 3),
            ("input_sha256", "0" * 64),
            ("extra", 1),
        ):
            data = receipt_data()
            data["sources"][0]["ordering_claim"][field] = value
            self.check_data(data)

    def test_heading_depth_and_root_claims_must_be_possible(self):
        data = receipt_data()
        data["sources"][0]["manifest"]["spec"]["expected_max_depth"] = 5
        self.check_data(data)

    def test_validated_claims_are_not_observed_bytes(self):
        data = receipt_data()
        data["sources"][0]["archive_size_bytes"] += 10
        report = self.check_data(data, "RECEIPT_VERIFIED")
        self.assertEqual(report.as_dict()["archive_verification"], "NOT_RUN")
        # Pinning a new claim is not a signature or proof of its contents.

    def test_no_mutation_or_normalization_of_receipt(self):
        raw, digest = fixture()
        original = bytes(raw)
        verify_receipt(raw, expected_sha256=digest, as_of=AS_OF)
        self.assertEqual(raw, original)
        self.assertIn(b"\r\n", raw)
        self.assertIn("مرجع".encode(), raw)
