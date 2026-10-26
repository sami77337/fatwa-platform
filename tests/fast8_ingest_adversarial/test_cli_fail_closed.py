"""Real CLI failures, stale bundles, and one unmasked legacy diagnostic regression."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.content_intake import diagnostic_cli
from tools.fast8_ingest_adversarial.fixtures import (
    FORMATS,
    MARKER,
    encode,
    intake_row,
    segment_row,
)

ROOT = Path(__file__).resolve().parents[2]


class CommandBoundaryTests(unittest.TestCase):
    def setUp(self):
        # All temporary writes remain in this lane, even for export beneath cwd.
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-", dir=Path(__file__).parent)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def run_cli(self, module, *arguments):
        return subprocess.run(
            [sys.executable, "-B", "-m", module, *map(str, arguments)],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            timeout=20,
            check=False,
        )

    def source(self, raw, suffix=".json", stem="synthetic"):
        path = self.directory / (stem + suffix)
        path.write_bytes(raw)
        return path

    def diagnostic_args(self, path):
        return ("diagnose", "--synthetic-fixtures-only", "--batch", "SYN-batch", path)

    def test_legacy_export_with_late_invalid_row_creates_no_partial_bundle(self):
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                raw = encode([intake_row("SYN-good"), intake_row("SYN-bad", question="")], suffix)
                path = self.source(raw, suffix)
                bundle = self.directory / ("not-created" + suffix)
                result = self.run_cli("tools.content_intake", "export", path, "--bundle", bundle)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
                self.assertFalse(bundle.exists())
                self.assertEqual(path.read_bytes(), raw)

    def test_legacy_check_rejects_stale_source_bom_with_identical_accepted_items(self):
        for suffix in FORMATS:
            with self.subTest(format=suffix):
                raw = encode([intake_row()], suffix, bom=False)
                path = self.source(raw, suffix)
                bundle = self.directory / ("legacy-bundle" + suffix)
                result = self.run_cli("tools.content_intake", "export", path, "--bundle", bundle)
                self.assertEqual(result.returncode, 0, result.stdout)
                before = {p.name: p.read_bytes() for p in bundle.iterdir()}
                path.write_bytes(b"\xef\xbb\xbf" + raw)
                result = self.run_cli("tools.content_intake", "check", path, "--bundle", bundle)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "bundle differs from deterministic input-derived output",
                )
                self.assertEqual({p.name: p.read_bytes() for p in bundle.iterdir()}, before)
                self.assertEqual(path.read_bytes(), b"\xef\xbb\xbf" + raw)

    def test_diagnostic_check_rejects_stale_equivalent_json_source_bytes(self):
        raw = encode([intake_row()], ".json", bom=False)
        path = self.source(raw)
        bundle = self.directory / "diagnostic-bundle"
        args = self.diagnostic_args(path)
        exported = self.run_cli("tools.content_intake", *args, "--export-bundle", bundle)
        self.assertEqual(exported.returncode, 0, exported.stdout)
        before = {p.name: p.read_bytes() for p in bundle.iterdir()}
        for changed in (
            b"\xef\xbb\xbf" + raw,
            raw.replace(b"\r\n", b"\n"),
            raw.replace("أ".encode(), b"\\u0623"),
        ):
            with self.subTest(sha256=hashlib.sha256(changed).hexdigest()):
                self.assertEqual(json.loads(raw), json.loads(changed))
                self.assertNotEqual(changed, raw)
                path.write_bytes(changed)
                result = self.run_cli("tools.content_intake", *args, "--check-bundle", bundle)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error_code"], "bundle: deterministic_output_mismatch"
                )
                self.assertEqual(path.read_bytes(), changed)
                self.assertEqual({p.name: p.read_bytes() for p in bundle.iterdir()}, before)
        path.write_bytes(raw)
        checked = self.run_cli("tools.content_intake", *args, "--check-bundle", bundle)
        self.assertEqual(checked.returncode, 0)
        self.assertEqual(checked.stdout, exported.stdout)

    def test_forged_manifest_cannot_bless_modified_diagnostic_artifact(self):
        path = self.source(encode([intake_row()], ".json"))
        args = self.diagnostic_args(path)
        bundle = self.directory / "forged-bundle"
        exported = self.run_cli("tools.content_intake", *args, "--export-bundle", bundle)
        self.assertEqual(exported.returncode, 0, exported.stdout)
        original = {p.name: p.read_bytes() for p in bundle.iterdir()}
        for name in ("diagnostics.json", "rows.jsonl", "recovery.txt"):
            with self.subTest(artifact=name):
                for filename, data in original.items():
                    (bundle / filename).write_bytes(data)
                changed = original[name] + b" "
                (bundle / name).write_bytes(changed)
                manifest = json.loads(original["manifest.json"])
                manifest["outputs"][name] = {
                    "sha256": hashlib.sha256(changed).hexdigest(),
                    "bytes": len(changed),
                }
                (bundle / "manifest.json").write_bytes(
                    (
                        json.dumps(
                            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                        )
                        + "\n"
                    ).encode()
                )
                for filename, metadata in manifest["outputs"].items():
                    artifact = (bundle / filename).read_bytes()
                    self.assertEqual(metadata["sha256"], hashlib.sha256(artifact).hexdigest())
                    self.assertEqual(metadata["bytes"], len(artifact))
                result = self.run_cli("tools.content_intake", *args, "--check-bundle", bundle)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["error_code"], "bundle: deterministic_output_mismatch"
                )

    def test_partial_diagnostic_write_reports_failure_and_bundle_never_checks_valid(self):
        raw = encode([intake_row()], ".json")
        path = self.source(raw)
        bundle = self.directory / "partial-bundle"
        original_open = Path.open

        def fail_second_write(target, mode="r", *args, **kwargs):
            if target == bundle / "rows.jsonl" and mode == "xb":
                raise OSError(MARKER)
            return original_open(target, mode, *args, **kwargs)

        output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        self.addCleanup(output.close)
        with patch.object(Path, "open", fail_second_write), patch.object(sys, "stdout", output):
            code = diagnostic_cli.main(
                [
                    "--synthetic-fixtures-only",
                    "--batch",
                    "SYN-batch",
                    str(path),
                    "--export-bundle",
                    str(bundle),
                ]
            )
        self.assertEqual(code, 1)
        payload = output.buffer.getvalue()
        self.assertEqual(json.loads(payload)["error_code"], "LOCAL_FILE_OPERATION_FAILED")
        self.assertNotIn(MARKER.encode(), payload)
        self.assertNotIn(str(path).encode(), payload)
        self.assertEqual(path.read_bytes(), raw)
        # No claim of atomic cleanup: the existing exporter can leave partial files.
        result = self.run_cli(
            "tools.content_intake", *self.diagnostic_args(path), "--check-bundle", bundle
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error_code"], "LOCAL_FILE_OPERATION_FAILED")

    def test_prepared_cli_partial_files_keep_order_hashes_and_safe_diagnostics(self):
        raw = encode([intake_row("SYN-first")], ".csv")
        first = self.source(raw, ".csv", "first")
        bad_raw = (MARKER + "\r\n").encode() + b"\xff"
        bad = self.source(bad_raw, ".jsonl", "bad")
        missing = self.directory / (MARKER + ".json")
        last_raw = encode([intake_row("SYN-last")], ".json")
        last = self.source(last_raw, ".json", "last")
        result = self.run_cli(
            "apps.prepared_pipeline", "--synthetic-fixtures-only", first, bad, missing, last
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        report = json.loads(result.stdout)
        self.assertEqual(
            [b["batch_id"] for b in report["batches"]], [f"input-{i:04d}" for i in range(1, 5)]
        )
        self.assertEqual(
            [b["error_code"] for b in report["batches"]],
            [None, "MALFORMED_INPUT", "SOURCE_READ_FAILED", None],
        )
        self.assertEqual(
            [b["input_sha256"] for b in report["batches"]],
            [
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256(bad_raw).hexdigest(),
                None,
                hashlib.sha256(last_raw).hexdigest(),
            ],
        )
        self.assertEqual(report["summary"]["draft_count"], 2)
        self.assertNotIn(MARKER.encode(), result.stdout)
        self.assertNotIn(str(self.directory).encode(), result.stdout)
        for path, original in ((first, raw), (bad, bad_raw), (last, last_raw)):
            self.assertEqual(path.read_bytes(), original)

    def test_transcript_cli_late_bad_row_emits_no_partial_report_or_prepared_export(self):
        for suffix in FORMATS:
            for export in ("report", "prepared"):
                with self.subTest(format=suffix, export=export):
                    rows = [segment_row(), segment_row(source_id=MARKER, fabricated=False)]
                    raw = encode(rows, suffix)
                    path = self.source(raw, suffix)
                    result = self.run_cli(
                        "tools.transcript_pipeline",
                        path,
                        "--synthetic-fixtures-only",
                        "--export",
                        export,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(result.stderr, b"TRANSCRIPT_VALIDATION_FAILED\n")
                    self.assertEqual(path.read_bytes(), raw)

    def test_legacy_duplicate_key_diagnostic_does_not_echo_submitted_key(self):
        # Strict negative contract: intentionally NOT skipped/xfail on the reviewed base.
        # cli.main currently exposes the submitted key via str(exc); fix belongs upstream.
        raw = ('[{"' + MARKER + '":1,"' + MARKER + '":2}]').encode()
        path = self.source(raw)
        result = self.run_cli("tools.content_intake", "validate", path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "INVALID")
        self.assertEqual(path.read_bytes(), raw)
        self.assertNotIn(MARKER.encode(), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
