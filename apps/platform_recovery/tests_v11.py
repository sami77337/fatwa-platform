"""Focused V11 encrypted recovery + cross-process maintenance/quarantine drills."""

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

from cryptography.fernet import Fernet

from . import tests as legacy


class V11RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        legacy.RecoveryTests.setup_records.__func__(cls)
        from . import admin, encrypted, maintenance

        cls.admin, cls.encrypted, cls.maintenance = admin, encrypted, maintenance
        cls.keys = tempfile.TemporaryDirectory(prefix="v11-synthetic-keys-")
        cls.addClassCleanup(cls.keys.cleanup)
        cls.key = Path(cls.keys.name) / "backup.key"
        encrypted.generate_key(path=cls.key, synthetic_fixtures_only=True)
        cls.control = cls.root / "maintenance"
        cls.control.mkdir(mode=0o700)
        maintenance.initialize(root=cls.control, storage=cls.storage, synthetic_fixtures_only=True)
        maintenance.enter(root=cls.control, synthetic_fixtures_only=True)
        cls.sealed = cls.seal()
        with cls.service.connect() as database:
            cls.manifest = {"postgres_major": database.info.server_version // 10000}
        if list(cls.root.rglob("database.dump")):
            raise AssertionError("V11 fixture must not create a plaintext backup")

    @classmethod
    def seal(cls):
        return cls.encrypted.snapshot(
            scratch=cls.root,
            storage=cls.storage,
            pg_bin=legacy.PG_BIN,
            key_file=cls.key,
            maintenance_root=cls.control,
            synthetic_fixtures_only=True,
        )

    def setUp(self):
        current = self.maintenance.status(root=self.control)
        if current["phase"] != "FROZEN":
            self.maintenance.enter(root=self.control, synthetic_fixtures_only=True)

    def resume(self):
        current = self.maintenance.status(root=self.control)
        return self.maintenance.resume(
            root=self.control,
            expected_generation=current["generation"],
            confirmed=True,
            synthetic_fixtures_only=True,
        )

    def restore(self, bundle=None, key=None):
        backup = bundle or self.sealed
        return self.encrypted.restore(
            bundle=backup["bundle"],
            expected_ciphertext_sha256=backup["ciphertext_sha256"],
            key_file=key or self.key,
            scratch=self.root,
            pg_bin=legacy.PG_BIN,
            synthetic_fixtures_only=True,
        )

    def databases(self):
        with self.service.connect() as db:
            return db.execute("SELECT oid,datname FROM pg_database ORDER BY oid").fetchall()

    def current_baseline(self):
        with self.service.connect() as db:
            return self.service.baseline(db)

    def custom_sealed(self, token):
        directory = Path(tempfile.mkdtemp(prefix="tampered-sealed-", dir=self.root))
        self.service.write_file(directory / "backup.fernet", token)
        pin = self.service.digest(token)
        self.service.write_file(directory / "COMPLETE", pin.encode())
        return {"bundle": str(directory), "ciphertext_sha256": pin}

    def test_01_encrypted_restore_reopens_bytes_schema_and_permissions(self):
        before = self.current_baseline()
        files_before = set(self.root.rglob("database.dump"))
        sealed = self.seal()
        self.assertEqual(
            set(Path(sealed["bundle"]).iterdir()),
            {Path(sealed["bundle"]) / "backup.fernet", Path(sealed["bundle"]) / "COMPLETE"},
        )
        self.assertEqual(set(self.root.rglob("database.dump")), files_before)
        token = (Path(sealed["bundle"]) / "backup.fernet").read_bytes()
        self.assertNotIn(self.attachment_raw, token)
        self.assertNotIn(self.key.read_bytes(), token)
        result = self.restore(sealed)
        env = {
            **os.environ,
            "PGDATABASE": result["database"],
            "PGTESTDATABASE": "test_" + result["database"],
            "RECOVERY_PRIVATE_ROOT": result["private_root"],
        }
        fixture = {
            "receipt": self.receipt,
            "other": self.other,
            "attachment": self.attachment,
            "attachment_hex": self.attachment_raw.hex(),
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
        self.assertEqual(self.current_baseline(), before)
        self.assertEqual(set(self.root.rglob("database.dump")), files_before)
        self.assertEqual(
            self.admin.inspect_restore(target=result["target"], synthetic_fixtures_only=True)[
                "state"
            ],
            "READY_RECORDED",
        )

    def test_02_wrong_key_and_authenticated_ciphertext_damage_precede_database_creation(self):
        key = Path(self.keys.name) / "wrong.key"
        self.encrypted.generate_key(path=key, synthetic_fixtures_only=True)
        before = self.databases()
        with self.assertRaisesRegex(self.service.RecoveryError, "backup_authentication_failed"):
            self.restore(key=key)
        token = bytearray((Path(self.sealed["bundle"]) / "backup.fernet").read_bytes())
        token[len(token) // 2] = ord("A") if token[len(token) // 2] != ord("A") else ord("B")
        for damaged in (bytes(token), bytes(token[:30])):
            # Recompute the outer hash to prove Fernet authentication itself rejects tampering.
            with self.assertRaisesRegex(self.service.RecoveryError, "backup_authentication_failed"):
                self.restore(self.custom_sealed(damaged))
        self.assertEqual(self.databases(), before)

    def test_03_missing_corrupt_decrypted_asset_and_extra_paths_fail_closed(self):
        cipher = Fernet(self.key.read_bytes())
        raw = cipher.decrypt((Path(self.sealed["bundle"]) / "backup.fernet").read_bytes())
        before = self.databases()
        for damage in ("missing", "corrupt", "extra"):
            data = json.loads(raw)
            name = next(key for key in data["files"] if key.startswith("objects/"))
            if damage == "missing":
                del data["files"][name]
            elif damage == "corrupt":
                data["files"][name] = base64.b64encode(b"corrupt original").decode()
            else:
                data["files"]["../escaped"] = base64.b64encode(b"invalid").decode()
            bad = self.custom_sealed(cipher.encrypt(self.service.canonical(data)))
            with self.assertRaises((self.service.RecoveryError, ValueError)):
                self.restore(bad)
        self.assertEqual(self.databases(), before)
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_04_maintenance_drains_real_writer_then_rejects_new_writes_and_gc(self):
        self.resume()
        script = """
import django, json, sys
django.setup()
from apps.platform_recovery.maintenance import mutation_guard
from apps.case_attachments.tests import new_case
root = json.loads(sys.stdin.readline())
with mutation_guard(root=root, synthetic_fixtures_only=True):
    print('ADMITTED', flush=True)
    sys.stdin.readline()
    new_case()
print('WRITE_COMMITTED', flush=True)
"""
        child = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            child.stdin.write(json.dumps(str(self.control)) + "\n")
            child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), "ADMITTED")
            state = self.maintenance.enter(root=self.control, synthetic_fixtures_only=True)
            self.assertEqual(state["phase"], "DRAINING")
            for operation in ("WRITE", "GC"):
                with self.assertRaisesRegex(
                    self.service.RecoveryError, "maintenance_writes_blocked"
                ):
                    with self.maintenance.mutation_guard(
                        root=self.control, operation=operation, synthetic_fixtures_only=True
                    ):
                        self.fail("blocked operation entered")
            child.stdin.write("finish\n")
            child.stdin.flush()
            stdout, stderr = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn("WRITE_COMMITTED", stdout)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
        self.assertEqual(
            self.maintenance.enter(root=self.control, synthetic_fixtures_only=True)["phase"],
            "FROZEN",
        )
        sealed = self.seal()
        self.assertEqual(
            self.encrypted.verify(
                bundle=sealed["bundle"],
                expected_ciphertext_sha256=sealed["ciphertext_sha256"],
                key_file=self.key,
            )["state"],
            "VERIFIED",
        )

    def test_05_nested_guard_commits_and_resume_cannot_race_backup(self):
        from django.db import transaction

        self.resume()
        with self.maintenance.mutation_guard(root=self.control, synthetic_fixtures_only=True):
            with transaction.atomic():
                with self.maintenance.mutation_guard(
                    root=self.control, synthetic_fixtures_only=True
                ):
                    pass
        state = self.maintenance.enter(root=self.control, synthetic_fixtures_only=True)
        with self.maintenance.frozen(root=self.control, storage=self.storage):
            with self.assertRaisesRegex(self.service.RecoveryError, "maintenance_busy"):
                self.maintenance.resume(
                    root=self.control,
                    expected_generation=state["generation"],
                    confirmed=True,
                    synthetic_fixtures_only=True,
                )
        with self.assertRaisesRegex(self.service.RecoveryError, "maintenance_generation_mismatch"):
            self.maintenance.resume(
                root=self.control,
                expected_generation="stale",
                confirmed=True,
                synthetic_fixtures_only=True,
            )

    def test_06_snapshot_hard_crash_keeps_gate_closed_and_only_ciphertext(self):
        paths = set(self.root.iterdir())
        script = """
import django, json, os, sys
django.setup()
from apps.platform_recovery import service, encrypted
from apps.private_media.filesystem import FileSystemStorage
args = json.load(sys.stdin)
args['storage'] = FileSystemStorage(args['storage'], synthetic_fixtures_only=True)
service.checkpoint = lambda stage: os._exit(73) if stage == 'encrypted_before_complete' else None
encrypted.snapshot(**args)
"""
        args = {
            "scratch": str(self.root),
            "storage": str(self.storage.root),
            "pg_bin": legacy.PG_BIN,
            "key_file": str(self.key),
            "maintenance_root": str(self.control),
            "synthetic_fixtures_only": True,
        }
        child = subprocess.run(
            [sys.executable, "-c", script], input=json.dumps(args), text=True, capture_output=True
        )
        self.assertEqual(child.returncode, 73, child.stderr)
        new = (set(self.root.iterdir()) - paths).pop()
        self.assertEqual(set(os.listdir(new)), {"backup.fernet"})
        self.assertEqual(self.encrypted.status(bundle=new)["state"], "INCOMPLETE")
        self.assertEqual(self.maintenance.status(root=self.control)["phase"], "FROZEN")
        self.resume()

    def crash_restore(self, stage):
        paths = set(self.root.glob("restore-*"))
        script = """
import django, json, os, sys
django.setup()
from apps.platform_recovery import service, encrypted
args = json.load(sys.stdin)
stage = args.pop('stage')
service.checkpoint = lambda current: os._exit(73) if current == stage else None
encrypted.restore(**args)
"""
        args = {
            "stage": stage,
            "bundle": self.sealed["bundle"],
            "expected_ciphertext_sha256": self.sealed["ciphertext_sha256"],
            "key_file": str(self.key),
            "scratch": str(self.root),
            "pg_bin": legacy.PG_BIN,
            "synthetic_fixtures_only": True,
        }
        child = subprocess.run(
            [sys.executable, "-c", script], input=json.dumps(args), text=True, capture_output=True
        )
        self.assertEqual(child.returncode, 73, child.stderr)
        return (set(self.root.glob("restore-*")) - paths).pop()

    def test_07_nonce_proven_preparing_target_reconciles_after_real_process_death(self):
        before = self.databases()
        target = self.crash_restore("database_identity_before_journal")
        report = self.admin.inspect_restore(target=target, synthetic_fixtures_only=True)
        self.assertEqual(report["state"], "IDENTITY_RECONCILABLE")
        with self.assertRaisesRegex(self.service.RecoveryError, "inspection_changed"):
            self.admin.reconcile(
                target=target,
                expected_inspection_sha256="stale",
                confirmed=True,
                synthetic_fixtures_only=True,
            )
        with self.assertRaisesRegex(self.service.RecoveryError, "explicit_reconciliation_required"):
            self.admin.reconcile(
                target=target,
                expected_inspection_sha256=report["inspection_sha256"],
                synthetic_fixtures_only=True,
            )
        report = self.admin.reconcile(
            target=target,
            expected_inspection_sha256=report["inspection_sha256"],
            confirmed=True,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(report["state"], "OWNED_QUARANTINE")
        self.service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
        self.assertEqual(self.databases(), before)
        self.assertEqual(self.restore()["state"], "READY")

    def test_08_no_nonce_target_remains_unknown_and_never_adopted_or_deleted(self):
        target = self.crash_restore("database_created_before_identity")
        report = self.admin.inspect_restore(target=target, synthetic_fixtures_only=True)
        self.assertEqual(report["state"], "UNKNOWN_PRESERVED")
        before = self.databases()
        with self.assertRaisesRegex(self.service.RecoveryError, "quarantine_not_reconcilable"):
            self.admin.reconcile(
                target=target,
                expected_inspection_sha256=report["inspection_sha256"],
                confirmed=True,
                synthetic_fixtures_only=True,
            )
        with self.assertRaisesRegex(self.service.RecoveryError, "rollback_identity_mismatch"):
            self.service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
        self.assertEqual(self.databases(), before)

    def test_09_active_restore_is_not_reconciled_by_other_process(self):
        observed = []

        def inspect(stage):
            if stage == "database_created":
                target = max(self.root.glob("restore-*"), key=lambda p: p.stat().st_mtime_ns)
                command = [
                    sys.executable,
                    "-m",
                    "apps.platform_recovery",
                    "restore-status",
                    "--offline-synthetic",
                    "--target",
                    str(target),
                ]
                child = subprocess.run(command, text=True, capture_output=True)
                self.assertEqual(child.returncode, 0, child.stderr)
                observed.append(json.loads(child.stdout)["state"])

        with patch.object(self.service, "checkpoint", side_effect=inspect):
            self.restore()
        self.assertEqual(observed, ["BUSY"])

    def test_10_encrypted_restore_failure_rolls_back_database_and_preserves_partial_files(self):
        before = self.databases()
        paths = set(self.root.glob("restore-*"))

        def fail(stage):
            if stage == "assets_restored":
                raise OSError("synthetic interrupted restore")

        with patch.object(self.service, "checkpoint", side_effect=fail):
            with self.assertRaisesRegex(self.service.RecoveryError, "target_quarantined"):
                self.restore()
        target = (set(self.root.glob("restore-*")) - paths).pop()
        self.assertEqual(self.databases(), before)
        self.assertEqual(len(list((target / "private" / "objects").iterdir())), 2)
        self.assertEqual(self.restore()["state"], "READY")

    def test_11_keys_outside_artifacts_and_status_contains_no_private_payload(self):
        forbidden = self.root / "forbidden.key"
        self.service.write_file(forbidden, b"synthetic-placeholder-not-a-key")
        with self.assertRaisesRegex(self.service.RecoveryError, "key_inside_artifacts"):
            self.encrypted.snapshot(
                scratch=self.root,
                storage=self.storage,
                pg_bin=legacy.PG_BIN,
                key_file=forbidden,
                maintenance_root=self.control,
                synthetic_fixtures_only=True,
            )
        command = [
            sys.executable,
            "-m",
            "apps.platform_recovery",
            "backup-status",
            "--offline-synthetic",
            "--bundle",
            self.sealed["bundle"],
        ]
        child = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(
            json.loads(child.stdout),
            {"state": "SEALED_UNAUTHENTICATED", "authenticated": False, "algorithm": "Fernet"},
        )
        self.assertNotIn(self.receipt["token"], child.stdout)
        self.assertNotIn(str(self.key), child.stdout)
        self.assertNotIn("manifest", child.stdout)

    def test_12_copied_context_cannot_reuse_expired_mutation_lease(self):
        from contextvars import copy_context

        self.resume()
        with self.maintenance.mutation_guard(root=self.control, synthetic_fixtures_only=True):
            copied = copy_context()
        self.maintenance.enter(root=self.control, synthetic_fixtures_only=True)

        def mutate():
            with self.maintenance.mutation_guard(root=self.control, synthetic_fixtures_only=True):
                self.fail("copied context bypassed maintenance")

        with self.assertRaisesRegex(self.service.RecoveryError, "maintenance_writes_blocked"):
            copied.run(mutate)

    def test_13_copied_context_cannot_reuse_expired_target_operation(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from threading import Event

        target = Path(tempfile.mkdtemp(prefix="restore-lock-", dir=self.root))
        with self.service.target_operation(target):
            copied = copy_context()
        started, release = Event(), Event()

        def hold():
            with self.service.target_operation(target):
                started.set()
                release.wait(10)

        def enter():
            with self.service.target_operation(target):
                self.fail("expired operation lease bypassed a live lock")

        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(hold)
            self.assertTrue(started.wait(5))
            try:
                with self.assertRaisesRegex(self.service.RecoveryError, "target_operation_busy"):
                    copied.run(enter)
            finally:
                release.set()
            task.result()

    def test_14_missing_nonce_never_claims_unknown_database(self):
        target = self.crash_restore("database_created_before_identity")
        state = json.loads((target / "journal.json").read_text())
        with self.service.connect() as db:
            state["oid"] = db.execute(
                "SELECT oid FROM pg_database WHERE datname=%s", [state["database"]]
            ).fetchone()[0]
        state["nonce"] = None
        self.service.journal(target, state)
        before = self.databases()
        with self.assertRaisesRegex(self.service.RecoveryError, "restore_record_invalid"):
            self.admin.inspect_restore(target=target, synthetic_fixtures_only=True)
        with self.assertRaisesRegex(self.service.RecoveryError, "rollback_identity_mismatch"):
            self.service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
        self.assertEqual(self.databases(), before)

    def test_15_encrypted_backup_restores_in_independent_new_postgres_cluster(self):
        fixture = {
            "receipt": self.receipt,
            "other": self.other,
            "attachment": self.attachment,
            "attachment_hex": self.attachment_raw.hex(),
        }
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "infra.dev.with_casework_postgres",
                "--pg-bin",
                legacy.PG_BIN,
                "--major",
                str(self.manifest["postgres_major"]),
                "--settings",
                "config.settings.campaign_review",
                "--",
                sys.executable,
                "-m",
                "apps.platform_recovery.verify_fixture",
                "--restore-bundle",
                self.sealed["bundle"],
                "--ciphertext-sha256",
                self.sealed["ciphertext_sha256"],
                "--key-file",
                str(self.key),
                "--scratch",
                str(self.root),
                "--pg-bin",
                legacy.PG_BIN,
            ],
            input=json.dumps(fixture, default=str),
            text=True,
            capture_output=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("RESTORED_SERVICE_CHECKS_PASS", child.stdout)

    def test_16_unconfigured_binding_and_unfrozen_snapshot_fail_closed(self):
        from django.test import override_settings

        with override_settings(FATWA_RECOVERY_MAINTENANCE_ROOT=None):
            with self.assertRaisesRegex(self.service.RecoveryError, "maintenance_unconfigured"):
                with self.maintenance.mutation_guard(synthetic_fixtures_only=True):
                    pass
        with patch.object(self.maintenance, "_identity", return_value={"wrong": "database"}):
            with self.assertRaisesRegex(self.service.RecoveryError, "maintenance_binding_mismatch"):
                self.maintenance.status(root=self.control)
        self.resume()
        with self.assertRaisesRegex(self.service.RecoveryError, "maintenance_not_frozen"):
            self.seal()
        self.maintenance.enter(root=self.control, synthetic_fixtures_only=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", required=True)
    args, remaining = parser.parse_known_args()
    legacy.PG_BIN = args.pg_bin
    legacy.setup()
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
