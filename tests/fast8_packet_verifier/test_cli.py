"""Executable CLI evidence with no Django setup and unchanged input files."""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from apps.editorial_export.services import build_export, encode_json
from apps.editorial_workbench.packets import MAX_PACKET_BYTES, serialize_packet


class PacketCliTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        bundle = build_export(synthetic_fixtures_only=True)
        packet = next(
            e["packet"]
            for e in bundle.report()["cases"]
            if e["packet"]["identity"]["case_key"] == "history"
        )
        self.packet = self.directory / "packet.json"
        self.manifest = self.directory / "manifest.json"
        self.packet.write_bytes(serialize_packet(packet))
        self.manifest.write_bytes(bundle.file("manifest.json"))
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"DJANGO_SETTINGS_MODULE", "FATWA_PRODUCTION"}
        }

    def run_cli(self, *, acknowledge=True):
        command = [
            sys.executable,
            "-B",
            "-m",
            "apps.fast8_packet_verifier",
            "--packet",
            str(self.packet),
            "--manifest",
            str(self.manifest),
            "--case-key",
            "history",
        ]
        if acknowledge:
            command.append("--synthetic-fixtures-only")
        return subprocess.run(command, capture_output=True, env=self.env, timeout=30)

    def assert_error(self, code):
        result = self.run_cli()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr.strip(), ("packet_verify: " + code).encode())
        return result

    def test_actual_cli_is_deterministic_and_read_only(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        first, second = self.run_cli(), self.run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, b"")
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(json.loads(first.stdout)["status"], "VERIFIED")
        self.assertEqual(first.stdout, encode_json(json.loads(first.stdout)))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_cli_unicode_and_revision_tampering_returns_exact_private_safe_codes(self):
        packet = json.loads(self.packet.read_bytes())
        packet["snapshots"][0]["title"] = "SYNTHETIC_SECRET_DO_NOT_ECHO"
        self.packet.write_bytes(serialize_packet(packet))
        self.assert_error("revision_digest_mismatch")
        self.packet.write_bytes(b'{"private":"\\ud800"}\n')
        self.assert_error("invalid_utf8")

    def test_missing_directory_and_size_inputs_fail_without_traceback(self):
        self.packet.unlink()
        self.assert_error("input_io_error")
        self.packet.mkdir()
        self.assert_error("regular_file_required")
        self.packet.rmdir()
        self.packet.write_bytes(b"x" * (MAX_PACKET_BYTES + 1))
        self.assert_error("byte_limit")

    def test_symlink_and_reparse_metadata_are_rejected_before_open(self):
        from apps.fast8_packet_verifier.__main__ import read_input
        from apps.fast8_packet_verifier.services import PacketVerificationError

        for metadata in (
            SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0),
            SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=1024),
        ):
            with (
                patch.object(Path, "lstat", return_value=metadata),
                patch("os.open", side_effect=AssertionError("must not open")),
                patch.object(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024, create=True),
            ):
                with self.assertRaisesRegex(PacketVerificationError, "regular_file_required"):
                    read_input(self.packet, MAX_PACKET_BYTES)

    def test_production_and_missing_acknowledgement_fail_before_io(self):
        self.packet.unlink()
        self.env["FATWA_PRODUCTION"] = "1"
        self.assert_error("synthetic_development_only")
        self.env.pop("FATWA_PRODUCTION")
        result = self.run_cli(acknowledge=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"Traceback", result.stderr)
