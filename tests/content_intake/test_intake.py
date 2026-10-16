import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.content_intake.cli import artifacts, normalize


def record(**changes):
    return dict(external_id="STAFF-001", question="سؤال اصطناعي للاختبار فقط؟",
                prepared_clip_url="https://example.invalid/finished.mp4",
                staff_notes="", reference_links=[], **changes)


class IntakeTests(unittest.TestCase):
    def test_committed_synthetic_expected_bundle(self):
        root = Path(__file__).resolve().parents[2] / "docs/dev/c1"
        # Git for Windows may check out synthetic text fixtures with CRLF.
        # Canonicalize only these checked-in test bytes, not user input.
        fixture_bytes = (root / "sample.csv").read_bytes().replace(b"\r\n", b"\n")
        outputs, manifest = artifacts(fixture_bytes, ".csv")
        for name, data in outputs.items():
            expected_bytes = (root / "expected" / name).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(expected_bytes, data)
        self.assertEqual(json.loads((root / "expected/manifest.json").read_bytes()), manifest)

    def test_validate_preview_and_invalid_export(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=root / "tests/content_intake") as directory:
            source = Path(directory) / "input.json"
            source.write_text(json.dumps([record()]), encoding="utf-8")
            for command in ("validate", "preview"):
                result = subprocess.run([sys.executable, "-m", "tools.content_intake",
                                         command, str(source)], cwd=root, capture_output=True)
                self.assertEqual(result.returncode, 0)
                self.assertIsInstance(json.loads(result.stdout), dict)
            source.write_text('[{"external_id":"x","question":""}]', encoding="utf-8")
            bundle = Path(directory) / "rejected"
            result = subprocess.run([sys.executable, "-m", "tools.content_intake", "export",
                                     str(source), "--bundle", str(bundle)], cwd=root,
                                    capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(bundle.exists())

    def test_arabic_bom_rtl_preserved(self):
        row = record()
        row["question"] = "\u200fسؤال تجريبي؟"
        raw = b"\xef\xbb\xbf" + json.dumps([row], ensure_ascii=False).encode()
        outputs, manifest = artifacts(raw, ".json")
        self.assertEqual(manifest["status"], "VALID")
        self.assertEqual(json.loads(outputs["intake.json"])["items"][0], row)

    def test_duplicate_and_blank(self):
        rows = [record(), record()]
        rows[1]["question"] = "  "
        _, findings = normalize(rows)
        self.assertEqual({f["code"] for f in findings}, {"duplicate_id", "required"})
        self.assertEqual({f["row"] for f in findings}, {2})

    def test_missing_media_review(self):
        row = record()
        row.pop("prepared_clip_url")
        _, manifest = artifacts(json.dumps([row]).encode(), ".json")
        self.assertEqual(manifest["status"], "REVIEW_REQUIRED")

    def test_reject_bad_shapes(self):
        for changes in ({"reference_links": [{"guess": "x"}]}, {"question": 2},
                        {"prepared_clip_url": "file:///tmp/video"},
                        {"prepared_clip_url": "https://user:pass@example.invalid/a"},
                        {"prepared_clip_url": "https://example.invalid:bad/a"},
                        {"unknown": "x"}, {"question": "\ud800"}):
            with self.subTest(changes=changes):
                row = record()
                row.update(changes)
                self.assertTrue(any(f["severity"] == "error" for f in normalize([row])[1]))

    def test_csv_formula_preserved_and_flagged(self):
        raw = 'external_id,title,staff_notes\nSTAFF-001,سؤال تجريبي,"=HYPERLINK(""x"")"\n'.encode()
        outputs, manifest = artifacts(raw, ".csv")
        self.assertEqual(manifest["status"], "REVIEW_REQUIRED")
        self.assertEqual(json.loads(outputs["intake.json"])["items"][0]["staff_notes"], '=HYPERLINK("x")')

    def test_strict_parsers(self):
        for raw, suffix in ((b"\xff", ".csv"), (b'external_id,external_id\nx,x\n', ".csv"),
                            (b'{"items":[],"items":[]}', ".json"),
                            (b'{"schema":"wrong","items":[]}', ".json")):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                artifacts(raw, suffix)

    def test_csv_extra_cells(self):
        _, manifest = artifacts(b'external_id,question\nx,q,extra\n', ".csv")
        self.assertEqual(manifest["status"], "INVALID")

    def test_manual_identity_and_roundtrip(self):
        row = record()
        row["reference_links"] = [{"source_id": "SYNTHETIC", "heading_id": "TEST-1"}]
        first, manifest = artifacts(json.dumps([row]).encode(), ".json")
        second, _ = artifacts(first["intake.jsonl"], ".jsonl")
        self.assertEqual(first, second)
        self.assertEqual(first, artifacts(json.dumps([row]).encode(), ".json")[0])
        self.assertEqual(manifest["row_count"], 1)

    def test_cli_export_check_tamper_and_no_overwrite(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            source = cwd / "input.json"
            source.write_text(json.dumps([record()]), encoding="utf-8")
            # Run from repository so module discovery is real; bundle lives beneath it.
            with tempfile.TemporaryDirectory(dir=root / "tests/content_intake") as bundle_parent:
                bundle = Path(bundle_parent) / "bundle"
                def run(command):
                    return subprocess.run([sys.executable, "-m", "tools.content_intake", command,
                                           str(source), "--bundle", str(bundle)], cwd=root,
                                          capture_output=True)
                self.assertEqual(run("export").returncode, 0)
                self.assertEqual(run("check").returncode, 0)
                self.assertEqual(run("export").returncode, 1)
                (bundle / "intake.jsonl").write_bytes(b"tampered")
                self.assertEqual(run("check").returncode, 1)


if __name__ == "__main__":
    unittest.main()
