"""Synthetic process-output fixtures; these tests do not prove real AV detection."""

import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, time
from unittest import TestCase
from unittest.mock import patch

from .clamav import ClamAVConfig, ClamAVScanner, DatabasePin, complete_report
from .contract import ScanInput, ScannerUnavailable


class ClamAVAdapterContractTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="SYNTHETIC-clamav-contract-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.exe = self.root / "SYNTHETIC-never-executed"
        self.exe.write_bytes(b"SYNTHETIC adapter fixture, not a ClamAV executable")
        self.exe.chmod(0o700)
        self.db = self.root / "db"
        self.db.mkdir(mode=0o700)
        pins = []
        for index, name in enumerate(("main.cvd", "daily.cvd", "bytecode.cvd")):
            header = (
                (
                    f"ClamAV-VDB:SYNTHETIC:{index + 1}:1:1:"
                    f"{'0' * 32}:SYNTHETIC:SYNTHETIC:{int(time())}"
                )
                .encode()
                .ljust(512, b" ")
            )
            raw = header + b"SYNTHETIC unsigned database, not real signatures"
            (self.db / name).write_bytes(raw)
            (self.db / name).chmod(0o400)
            pins.append(DatabasePin(name, sha256(raw).hexdigest(), len(raw)))
        self.config = ClamAVConfig(
            key="SYNTHETIC-adapter-contract",
            executable=str(self.exe),
            executable_sha256=sha256(self.exe.read_bytes()).hexdigest(),
            engine_version="SYNTHETIC-1",
            database_directory=str(self.db),
            databases=tuple(pins),
            max_daily_age_days=2,
            memory_bytes=1024 * 1024 * 1024,
        )
        self.raw = b"SYNTHETIC exact upload bytes"

    def request(self):
        return ScanInput(self.raw, sha256(self.raw).hexdigest(), len(self.raw), monotonic() + 3)

    def report(self, path):
        return (
            f"{path}: OK\n\n----------- SCAN SUMMARY -----------\n"
            "Known viruses: 3\nEngine version: SYNTHETIC-1\n"
            "Scanned directories: 0\nScanned files: 1\nInfected files: 0\n"
            "Data scanned: 0.00 MB\nData read: 0.00 MB (ratio 0.00:1)\n"
            "Time: 0.01 sec (0 m 0 s)\nStart Date: 2026:11:21 00:00:00\n"
            "End Date: 2026:11:21 00:00:00\n"
        ).encode()

    def execute(self, scanner, transform=lambda value: value, code=0):
        def fake(command, root, deadline):
            path = Path(command[-1])
            self.assertEqual(path.read_bytes(), self.raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            self.assertIn("--official-db-only=yes", command)
            self.assertIn("--alert-exceeds-max=yes", command)
            self.assertIn("--max-scantime=0", command)
            self.assertIn("--disable-cache", command)
            self.assertIn("--fail-if-cvd-older-than=2", command)
            return code, transform(self.report(path))

        with patch.object(scanner, "_execute", side_effect=fake):
            return scanner.scan(self.request())

    def test_missing_binary_or_bad_database_is_unavailable_without_process(self):
        for config in (
            replace(self.config, executable=str(self.root / "missing")),
            replace(self.config, executable_sha256="0" * 64),
            replace(self.config, databases=self.config.databases[:2]),
        ):
            scanner = ClamAVScanner(config)
            with self.subTest(config=config), self.assertRaises(ScannerUnavailable):
                _ = scanner.spec
            with patch.object(scanner, "_execute") as execute:
                with self.assertRaises(ScannerUnavailable):
                    scanner.scan(self.request())
                execute.assert_not_called()

    def test_expired_cvd_header_and_changed_files_invalidate_saved_projection(self):
        scanner = ClamAVScanner(self.config)
        _ = scanner.spec
        with patch("apps.upload_security.clamav.time", return_value=time() + 3 * 86400):
            with self.assertRaises(ScannerUnavailable):
                _ = scanner.spec
        target = self.db / "daily.cvd"
        target.chmod(0o600)
        target.write_bytes(target.read_bytes()[:-1] + b"!")
        target.chmod(0o400)
        with self.assertRaises(ScannerUnavailable):
            _ = scanner.spec

    def test_empty_partial_wrong_engine_and_extra_warning_never_become_clean(self):
        for transform in (
            lambda report: b"",
            lambda report: report.replace(b"Scanned files: 1", b"Scanned files: 0"),
            lambda report: report.replace(b"Known viruses: 3", b"Known viruses: 0"),
            lambda report: report.replace(b"SYNTHETIC-1", b"OTHER-ENGINE"),
            lambda report: report + b"WARNING: scan skipped\n",
            lambda report: report.replace(b"Infected files: 0", b"Infected files: 1"),
            lambda report: report + b"Total errors: 1\n",
            lambda report: report + b"Scanned files: 1\n",
        ):
            with self.subTest(transform=transform):
                result = self.execute(ClamAVScanner(self.config), transform)
                self.assertEqual(result.status, "INCOMPLETE")
                self.assertFalse(result.complete)

    def test_complete_fixture_proves_only_command_and_exact_output_contract(self):
        scanner = ClamAVScanner(self.config)
        result = self.execute(scanner)
        self.assertEqual(result.status, "CLEAN")
        self.assertTrue(result.complete)
        self.assertEqual(result.sha256, sha256(self.raw).hexdigest())
        self.assertEqual(result.size, len(self.raw))
        self.assertEqual(result.spec, scanner.spec)
        self.assertEqual((result.scanned_files, result.loaded_signatures), (1, 3))

    def test_nonzero_error_and_detected_return_are_never_released(self):
        self.assertEqual(self.execute(ClamAVScanner(self.config), code=2).status, "UNAVAILABLE")
        self.assertEqual(self.execute(ClamAVScanner(self.config), code=1).status, "BLOCKED")

    def test_detected_summary_and_upstream_byte_units_keep_exact_coverage(self):
        def infected(report):
            return (
                report.replace(b": OK\n", b": SYNTHETIC.Signature FOUND\n")
                .replace(b"Infected files: 0", b"Infected files: 1")
                .replace(b"0.00 MB", b"68 B")
            )

        result = self.execute(ClamAVScanner(self.config), infected, code=1)
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(result.complete)
        self.assertEqual((result.scanned_files, result.loaded_signatures), (1, 3))

    def test_actual_154_report_keeps_aligned_end_date_without_accepting_partial_coverage(self):
        # Exact benign report from real hosted run 44910119961 / artifact
        # 14708539425. This parser replay is not a fresh engine execution.
        raw = (Path(__file__).with_name("fixtures") / "clamav-1.5.4-clean.txt").read_bytes()
        self.assertEqual(
            sha256(raw).hexdigest(),
            "ac4703a1d1cece9bbb4557eab8f3f397ce37d15c7a1532b940b7a1c7581c37fe",
        )
        path = "/tmp/fatwa-scan-kmvfz7cw/upload.original"
        self.assertEqual(complete_report(raw, path, "1.5.4"), 3628232)
        for bad in (
            raw.replace(b"Scanned files: 1", b"Scanned files: 0"),
            raw.replace(b"Known viruses: 3628232", b"Known viruses: 0"),
            raw.replace(b"Infected files: 0", b"Infected files: 1"),
            raw + b"WARNING: incomplete coverage\n",
            raw + b"Scanned files: 1\n",
        ):
            self.assertIsNone(complete_report(bad, path, "1.5.4"))

    def test_post_process_signature_change_and_timeout_discard_clean_output(self):
        scanner = ClamAVScanner(self.config)

        def change(report):
            (self.db / "unconfigured.hdb").write_bytes(b"SYNTHETIC")
            return report

        self.assertEqual(self.execute(scanner, change).status, "UNAVAILABLE")
        (self.db / "unconfigured.hdb").unlink()
        scanner = ClamAVScanner(self.config)
        with patch.object(scanner, "_execute", side_effect=TimeoutError):
            self.assertEqual(scanner.scan(self.request()).status, "UNAVAILABLE")

    def test_real_worker_deadline_kills_and_reaps_its_own_synthetic_child(self):
        scanner = ClamAVScanner(self.config)
        created = []
        actual = subprocess.Popen

        def capture(*args, **kwargs):
            process = actual(*args, **kwargs)
            created.append(process)
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(set(kwargs["env"]), {"PATH", "LANG", "LC_ALL", "TMPDIR"})
            return process

        with patch("apps.upload_security.clamav.subprocess.Popen", side_effect=capture):
            with self.assertRaises(TimeoutError):
                scanner._execute(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    self.root,
                    monotonic() + 0.1,
                )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].poll(), -9)

    def test_real_worker_exec_error_is_unavailable_and_cannot_masquerade_as_detection(self):
        scanner = ClamAVScanner(self.config)
        result = scanner.scan(self.request())
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertFalse(result.complete)
