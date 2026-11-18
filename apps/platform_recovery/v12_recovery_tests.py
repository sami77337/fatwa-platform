"""P0-only strict/compatibility and encrypted preflight tests on an owned PG17/18 cluster."""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import django
from cryptography.fernet import Fernet


class StrictRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from django.test import override_settings

        from apps.answer_media import services as answers
        from apps.answer_media.models import AnswerManifest
        from apps.answer_media.tests import audio_fixture
        from apps.case_attachments import services as attachments
        from apps.case_attachments.tests import new_case, staff_common
        from apps.casework import services as cases
        from apps.private_media.filesystem import FileSystemStorage

        from . import encrypted, maintenance, service

        cls.encrypted, cls.service = encrypted, service
        cls.tmp = tempfile.TemporaryDirectory(prefix="v12-recovery-")
        cls.keys = tempfile.TemporaryDirectory(prefix="v12-recovery-keys-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.addClassCleanup(cls.keys.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.storage = FileSystemStorage(cls.root / "source", synthetic_fixtures_only=True)
        configured = override_settings(
            FATWA_PRIVATE_MEDIA_STORAGE=cls.storage,
            FATWA_CASE_ATTACHMENTS_ENABLED=True,
            FATWA_ANSWER_MEDIA_ENABLED=True,
            FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
        )
        configured.enable()
        cls.addClassCleanup(configured.disable)
        cls.receipt, cls.other = new_case(), new_case()
        cls.raw = "أصل اصطناعي\r\nدون تغيير البايتات\n".encode()
        cls.attachment = attachments.upload(
            token=cls.receipt["token"],
            raw=cls.raw,
            filename="fixture.txt",
            media_type="text/plain",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        common = staff_common(cls.receipt)
        for _ in range(2):
            current = cases.read_case(**common)
            answers.save_multipart_answer(
                **common,
                text="جواب بشري اصطناعي",
                files=[audio_fixture()],
                expected_revision=current["revision"],
                expected_evidence_version=current["evidence_version"],
            )
        current = cases.read_case(**common)
        approved = cases.record_decision(
            **common,
            action="APPROVE",
            answer_id=current["answers"][-1]["id"],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        manifest = AnswerManifest.objects.get(answer_id=approved["approved_answer_id"])
        answers.release_private(
            **common,
            expected_revision=approved["revision"],
            expected_evidence_version=approved["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
        cls.control = cls.root / "control"
        cls.control.mkdir(mode=0o700)
        maintenance.initialize(root=cls.control, storage=cls.storage, synthetic_fixtures_only=True)
        maintenance.enter(root=cls.control, synthetic_fixtures_only=True)
        cls.key = Path(cls.keys.name) / "synthetic.key"
        encrypted.generate_key(path=cls.key, synthetic_fixtures_only=True)
        cls.sealed = encrypted.snapshot(
            scratch=cls.root,
            storage=cls.storage,
            pg_bin=PG_BIN,
            key_file=cls.key,
            maintenance_root=cls.control,
            synthetic_fixtures_only=True,
        )
        with service.connect() as db:
            cls.baseline = service.baseline(db)
        print(
            "V12_STRICT_BASELINE "
            + json.dumps(
                encrypted.verify(
                    bundle=cls.sealed["bundle"],
                    expected_ciphertext_sha256=cls.sealed["ciphertext_sha256"],
                    key_file=cls.key,
                ),
                sort_keys=True,
            ),
            flush=True,
        )

    def cli(self, arguments, *, compat=False):
        env = os.environ.copy()
        if compat:
            env["DJANGO_SETTINGS_MODULE"] = self.service.V10_TEST_SETTINGS
        return subprocess.run(
            [sys.executable, "-m", "apps.platform_recovery", *arguments, "--offline-synthetic"],
            env=env,
            text=True,
            capture_output=True,
        )

    def databases(self):
        with self.service.connect() as db:
            return db.execute("SELECT oid,datname FROM pg_database ORDER BY oid").fetchall()

    def restore(self, *, backup=None, key=None, pin=None):
        backup = backup or self.sealed
        return self.encrypted.restore(
            bundle=backup["bundle"],
            expected_ciphertext_sha256=pin if pin is not None else backup["ciphertext_sha256"],
            key_file=key or self.key,
            scratch=self.root,
            pg_bin=PG_BIN,
            synthetic_fixtures_only=True,
        )

    def verify_restored_services(self, restored):
        fixture = {
            "receipt": self.receipt,
            "other": self.other,
            "attachment": self.attachment,
            "attachment_hex": self.raw.hex(),
        }
        env = {
            **os.environ,
            "PGDATABASE": restored["database"],
            "PGTESTDATABASE": "test_" + restored["database"],
            "RECOVERY_PRIVATE_ROOT": restored["private_root"],
        }
        child = subprocess.run(
            [sys.executable, "-m", "apps.platform_recovery.verify_fixture"],
            input=json.dumps(fixture, default=str),
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("RESTORED_SERVICE_CHECKS_PASS", child.stdout)

    def test_01_plaintext_api_and_cli_are_closed_before_any_output_or_adapter_open(self):
        from django.test import override_settings

        before = set(self.root.iterdir())
        for flags in (
            {},
            {"FATWA_RECOVERY_ENCRYPTION_REQUIRED": True},
            {"FATWA_RECOVERY_ENCRYPTION_REQUIRED": False, "FATWA_RECOVERY_V10_TEST_COMPAT": True},
            {"FATWA_RECOVERY_ENCRYPTION_REQUIRED": 0, "FATWA_RECOVERY_V10_TEST_COMPAT": True},
            {"FATWA_RECOVERY_ENCRYPTION_REQUIRED": "false", "FATWA_RECOVERY_V10_TEST_COMPAT": True},
        ):
            with self.subTest(flags=flags), override_settings(**flags):
                with patch.object(self.service.PostgresTools, "run") as dump:
                    with self.assertRaisesRegex(
                        self.service.RecoveryError, "plaintext_recovery_disabled"
                    ):
                        self.service.snapshot(
                            scratch=self.root,
                            storage=self.storage,
                            pg_bin=PG_BIN,
                            synthetic_fixtures_only=True,
                            offline=True,
                        )
                    dump.assert_not_called()
        child = self.cli(
            [
                "legacy-snapshot",
                "--scratch",
                str(self.root),
                "--private-root",
                str(self.root / "must-not-create"),
                "--pg-bin",
                PG_BIN,
            ]
        )
        self.assertEqual(child.returncode, 1, child.stderr)
        self.assertEqual(
            json.loads(child.stdout), {"state": "FAILED", "code": "plaintext_recovery_disabled"}
        )
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertFalse(list(self.root.rglob("database.dump")))
        self.assertFalse(list(self.root.rglob("manifest.json")))

    def test_02_only_separate_v10_test_profile_allows_plaintext_and_restore(self):
        compat_root = Path(tempfile.mkdtemp(prefix="v10-compat-only-", dir=self.root))
        child = self.cli(
            [
                "legacy-snapshot",
                "--scratch",
                str(compat_root),
                "--private-root",
                str(self.storage.root),
                "--pg-bin",
                PG_BIN,
            ],
            compat=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        receipt = json.loads(child.stdout)
        self.service.verify_bundle(receipt["bundle"], receipt["manifest_sha256"])
        before_db, before_paths = self.databases(), set(compat_root.iterdir())
        args = [
            "legacy-restore",
            "--scratch",
            str(compat_root),
            "--pg-bin",
            PG_BIN,
            "--bundle",
            receipt["bundle"],
            "--manifest-sha256",
            receipt["manifest_sha256"],
        ]
        denied = self.cli(args)
        self.assertEqual(json.loads(denied.stdout)["code"], "plaintext_recovery_disabled")
        with self.assertRaisesRegex(self.service.RecoveryError, "plaintext_recovery_disabled"):
            self.service.restore(
                bundle=receipt["bundle"],
                expected_manifest_sha256=receipt["manifest_sha256"],
                scratch=compat_root,
                pg_bin=PG_BIN,
                synthetic_fixtures_only=True,
                offline=True,
            )
        self.assertEqual(self.databases(), before_db)
        self.assertEqual(set(compat_root.iterdir()), before_paths)
        restored = self.cli(args, compat=True)
        self.assertEqual(restored.returncode, 0, restored.stderr + restored.stdout)
        self.verify_restored_services(json.loads(restored.stdout))
        # Even the test-only profile cannot override an explicit strict=True.
        script = """
import django
django.setup()
from django.test import override_settings
from apps.platform_recovery.service import require_v10_test_profile, RecoveryError
with override_settings(FATWA_RECOVERY_ENCRYPTION_REQUIRED=True):
    try:
        require_v10_test_profile()
    except RecoveryError:
        print('STRICT_WINS')
    else:
        raise AssertionError('strict was bypassed')
"""
        child = subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "DJANGO_SETTINGS_MODULE": self.service.V10_TEST_SETTINGS},
            text=True,
            capture_output=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("STRICT_WINS", child.stdout)

    def test_03_strict_encrypted_roundtrip_retains_originals_permissions_and_schema(self):
        before_plaintext = set(self.root.rglob("database.dump")) | set(
            self.root.rglob("manifest.json")
        )
        sealed = self.encrypted.snapshot(
            scratch=self.root,
            storage=self.storage,
            pg_bin=PG_BIN,
            key_file=self.key,
            maintenance_root=self.control,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(set(os.listdir(sealed["bundle"])), {"backup.fernet", "COMPLETE"})
        self.assertNotIn(self.raw, (Path(sealed["bundle"]) / "backup.fernet").read_bytes())
        self.assertNotIn(
            self.key.read_bytes(), (Path(sealed["bundle"]) / "backup.fernet").read_bytes()
        )
        restored = self.restore(backup=sealed)
        self.assertEqual(restored["state"], "READY")
        self.verify_restored_services(restored)
        self.assertEqual(
            set(self.root.rglob("database.dump")) | set(self.root.rglob("manifest.json")),
            before_plaintext,
        )
        with self.service.connect() as db:
            self.assertEqual(self.service.baseline(db), self.baseline)

    def test_04_wrong_malformed_missing_keys_and_invalid_pins_create_no_target(self):
        wrong = Path(self.keys.name) / "wrong.key"
        self.encrypted.generate_key(path=wrong, synthetic_fixtures_only=True)
        short = Path(self.keys.name) / "short.key"
        self.service.write_file(short, b"synthetic-not-a-key")
        malformed = Path(self.keys.name) / "malformed.key"
        self.service.write_file(malformed, b"!" * 44)
        before_db, before_paths = self.databases(), set(self.root.iterdir())
        for key in (wrong, short, malformed, Path(self.keys.name) / "absent.key"):
            with (
                self.subTest(key=key.name),
                self.assertRaises((self.service.RecoveryError, OSError)),
            ):
                self.restore(key=key)
        for pin in ("", "bad", "0" * 64):
            with self.subTest(pin_length=len(pin)), self.assertRaises(self.service.RecoveryError):
                self.restore(pin=pin)
        self.assertEqual(self.databases(), before_db)
        self.assertEqual(set(self.root.iterdir()), before_paths)

    def write_token(self, token):
        directory = Path(tempfile.mkdtemp(prefix="tampered-", dir=self.root))
        self.service.write_file(directory / "backup.fernet", token)
        pin = self.service.digest(token)
        self.service.write_file(directory / "COMPLETE", pin.encode())
        return {"bundle": str(directory), "ciphertext_sha256": pin}

    def test_05_ciphertext_truncation_or_tamper_even_with_updated_hash_prevents_target(self):
        token = (Path(self.sealed["bundle"]) / "backup.fernet").read_bytes()
        damaged = bytearray(token)
        damaged[len(damaged) // 2] = (
            ord("A") if damaged[len(damaged) // 2] != ord("A") else ord("B")
        )
        for value in (token[:25], bytes(damaged)):
            backup = self.write_token(value)
            before_db, before_paths = self.databases(), set(self.root.iterdir())
            with self.assertRaisesRegex(self.service.RecoveryError, "backup_authentication_failed"):
                self.restore(backup=backup)
            self.assertEqual(self.databases(), before_db)
            self.assertEqual(set(self.root.iterdir()), before_paths)

    def test_06_authenticated_missing_or_corrupt_assets_and_bad_structure_still_fail(self):
        cipher = Fernet(self.key.read_bytes())
        raw = cipher.decrypt((Path(self.sealed["bundle"]) / "backup.fernet").read_bytes())
        for corruption in (
            "missing",
            "corrupt",
            "files-list",
            "envelope-list",
            "manifest",
            "extra-plain",
        ):
            data = json.loads(raw)
            key = next(k for k in data["files"] if k.startswith("objects/"))
            if corruption == "missing":
                del data["files"][key]
            elif corruption == "corrupt":
                data["files"][key] = base64.b64encode(b"wrong original").decode()
            elif corruption == "files-list":
                data["files"] = []
            elif corruption == "envelope-list":
                data = []
            elif corruption == "manifest":
                data["manifest_sha256"] = "0" * 64
            backup = self.write_token(cipher.encrypt(self.service.canonical(data)))
            if corruption == "extra-plain":
                self.service.write_file(
                    Path(backup["bundle"]) / "manifest.json", b"synthetic-placeholder"
                )
            before_db, before_paths = self.databases(), set(self.root.iterdir())
            with (
                self.subTest(corruption=corruption),
                self.assertRaises((self.service.RecoveryError, ValueError)),
            ):
                self.restore(backup=backup)
            self.assertEqual(self.databases(), before_db)
            self.assertEqual(set(self.root.iterdir()), before_paths)

    def test_07_key_repository_artifact_and_symlink_boundaries_remain_closed(self):
        before_db, before_paths = self.databases(), set(self.root.iterdir())
        # Model a checkout under /tmp without putting an actual key into the repository/artifacts.
        with patch.object(self.encrypted, "REPOSITORY_ROOT", Path(self.keys.name)):
            with self.assertRaisesRegex(self.service.RecoveryError, "key_inside_repository"):
                self.restore()
            new_key = Path(self.keys.name) / "must-not-generate.key"
            with self.assertRaisesRegex(self.service.RecoveryError, "key_inside_repository"):
                self.encrypted.generate_key(path=new_key, synthetic_fixtures_only=True)
            self.assertFalse(new_key.exists())
        linked = Path(self.keys.name) / "linked.key"
        linked.symlink_to(self.key)
        with self.assertRaisesRegex(self.service.RecoveryError, "key_path_invalid"):
            self.restore(key=linked)
        self.assertEqual(self.databases(), before_db)
        self.assertEqual(set(self.root.iterdir()), before_paths)
        bad_key = self.root / "not-a-key"
        self.service.write_file(bad_key, b"synthetic-placeholder")
        with self.assertRaisesRegex(self.service.RecoveryError, "key_inside_artifacts"):
            self.restore(key=bad_key)

    def test_08_cli_bad_key_reports_only_fixed_code_before_target_creation(self):
        key = Path(self.keys.name) / "invalid-cli.key"
        self.service.write_file(key, b"synthetic-invalid-key")
        before_db, before_paths = self.databases(), set(self.root.iterdir())
        child = self.cli(
            [
                "restore",
                "--scratch",
                str(self.root),
                "--pg-bin",
                PG_BIN,
                "--bundle",
                self.sealed["bundle"],
                "--ciphertext-sha256",
                self.sealed["ciphertext_sha256"],
                "--key-file",
                str(key),
            ]
        )
        self.assertEqual(child.returncode, 1, child.stderr)
        self.assertEqual(
            json.loads(child.stdout), {"state": "FAILED", "code": "fernet_key_invalid"}
        )
        self.assertEqual(child.stderr, "")
        self.assertNotIn(str(key), child.stdout)
        self.assertNotIn(self.receipt["token"], child.stdout)
        self.assertEqual(self.databases(), before_db)
        self.assertEqual(set(self.root.iterdir()), before_paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", required=True)
    args, remaining = parser.parse_known_args()
    PG_BIN = args.pg_bin
    django.setup()
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
