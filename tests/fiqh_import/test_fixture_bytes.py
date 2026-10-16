"""Disposable transport variants; immutable synthetic fixture and pins stay exact."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tools.fiqh_import.ingest import ValidationError, ingest, load_manifest

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureBytesTests(unittest.TestCase):
    def test_git_crlf_checkout_preserves_golden_fixture_bytes(self):
        original = (FIXTURES / "synthetic-five-level.json").read_bytes()
        manifest = load_manifest(FIXTURES / "synthetic-five-level.manifest.json")
        with tempfile.TemporaryDirectory(prefix="e5-checkout-") as scratch:
            root = Path(scratch)
            target = root / "synthetic-five-level.json"
            target.write_bytes(original)
            attributes = FIXTURES / ".gitattributes"
            if attributes.is_file():
                shutil.copyfile(attributes, root / ".gitattributes")
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True)
            git("init", "--quiet")
            git("-c", "core.autocrlf=false", "add", ".")
            target.unlink()
            git("-c", "core.autocrlf=true", "checkout-index", "--force", "--all")
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),
                             manifest.input_sha256)
            self.assertEqual(target.read_bytes(), original)
            self.assertTrue(ingest(target, manifest, profile="synthetic").report["valid"])
        self.assertEqual((FIXTURES / "synthetic-five-level.json").read_bytes(), original)

    def test_lf_crlf_bom_variants_hash_exact_bytes_without_mutating_original(self):
        original = (FIXTURES / "synthetic-five-level.json").read_bytes()
        manifest = load_manifest(FIXTURES / "synthetic-five-level.manifest.json")
        with tempfile.TemporaryDirectory(prefix="e5-variants-") as scratch:
            target = Path(scratch) / "variant.json"
            for newline in (b"\n", b"\r\n"):
                for bom in (b"", b"\xef\xbb\xbf"):
                    with self.subTest(newline=newline, bom=bool(bom)):
                        raw = bom + original.replace(b"\n", newline)
                        target.write_bytes(raw)
                        pin = hashlib.sha256(raw).hexdigest()
                        result = ingest(target, replace(manifest, input_sha256=pin),
                                        profile="synthetic")
                        self.assertEqual(result.report["input_sha256"], pin)
                        self.assertEqual(result.report["unique_valid_records"], 7)
                        self.assertEqual(target.read_bytes(), raw)
                        if pin != manifest.input_sha256:
                            with self.assertRaises(ValidationError):
                                ingest(target, manifest, profile="synthetic")
        self.assertEqual(hashlib.sha256(original).hexdigest(), manifest.input_sha256)
        self.assertEqual((FIXTURES / "synthetic-five-level.json").read_bytes(), original)
