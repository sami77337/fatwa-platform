"""Stdlib regressions for byte-pinned loopback preview CSS; no Django or DB."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.editorial_demo import asset_integrity as guard


class PreviewCssIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(guard.__file__).with_name("preview.css").read_bytes()

    def check_payload(self, payload, expected_error=None):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "preview.css"
            if payload is not None:
                target.write_bytes(payload)
            with patch.object(guard, "PREVIEW_CSS_PATH", target):
                if expected_error is None:
                    self.assertEqual(guard.verified_preview_css(), self.original)
                else:
                    with self.assertRaisesRegex(guard.AssetIntegrityError, expected_error):
                        guard.verified_preview_css()

    def test_original_bytes_are_pinned_and_returned_unchanged(self):
        self.assertEqual(len(self.original), guard.PREVIEW_CSS_SIZE)
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), guard.PREVIEW_CSS_SHA256)
        self.check_payload(self.original)

    def test_changed_byte_same_size_is_denied(self):
        payload = bytearray(self.original)
        payload[0] ^= 1
        self.check_payload(bytes(payload), "integrity_mismatch")

    def test_shortened_file_is_denied(self):
        self.check_payload(self.original[:-1], "integrity_mismatch")

    def test_appended_data_is_denied_with_bounded_read(self):
        self.check_payload(self.original + b"extra" * 100_000, "integrity_mismatch")

    def test_missing_file_is_denied(self):
        self.check_payload(None, "unavailable")

    def test_reencoded_line_endings_are_denied(self):
        self.assertIn(b"\n", self.original)
        self.check_payload(self.original.replace(b"\n", b"\r\n"), "integrity_mismatch")


if __name__ == "__main__":
    unittest.main()
