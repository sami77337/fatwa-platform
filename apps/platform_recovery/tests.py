"""Real PG17/18 integration tests, run in infra.dev.with_casework_postgres's fresh cluster.

python -m apps.platform_recovery.tests --pg-bin /path/to/postgresql/bin
The module uses the already migrated campaign profile; no pre-existing DB is reset.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import django


def setup():
    django.setup()


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setup_records()
        cls.setup_legacy_snapshot()

    @classmethod
    def setup_records(cls):
        """Canonical service fixture shared without choosing a recovery format."""
        from django.conf import settings
        from django.test import override_settings

        from apps.answer_media import services as answers
        from apps.answer_media.tests import audio_fixture
        from apps.case_attachments import services as attachments
        from apps.case_attachments.tests import new_case, staff_common
        from apps.casework import services as cases
        from apps.private_media.filesystem import FileSystemStorage

        from . import service

        cls.service = service
        cls.temp = tempfile.TemporaryDirectory(prefix="v10-recovery-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.storage = FileSystemStorage(cls.root / "source", synthetic_fixtures_only=True)
        cls.settings = override_settings(
            # Django's UserSettingsHolder otherwise masks this with None. Keep
            # the profile actually selected by the isolated process; do not
            # manufacture compatibility or alter encryption flags here.
            SETTINGS_MODULE=settings.SETTINGS_MODULE,
            FATWA_PRIVATE_MEDIA_STORAGE=cls.storage,
            FATWA_CASE_ATTACHMENTS_ENABLED=True,
            FATWA_ANSWER_MEDIA_ENABLED=True,
            FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
        )
        cls.settings.enable()
        cls.addClassCleanup(cls.settings.disable)
        cls.receipt = new_case()
        cls.other = new_case()
        cls.attachment_raw = "أصل اصطناعي\r\nمع الحفاظ على البايتات\n".encode()
        cls.attachment = attachments.upload(
            token=cls.receipt["token"],
            raw=cls.attachment_raw,
            filename="fixture.txt",
            media_type="text/plain",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        common = staff_common(cls.receipt)
        # Two retained answer revisions plus independent approval/private release.
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
        from apps.answer_media.models import AnswerManifest

        manifest = AnswerManifest.objects.get(answer_id=approved["approved_answer_id"])
        answers.release_private(
            **common,
            expected_revision=approved["revision"],
            expected_evidence_version=approved["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
    @classmethod
    def setup_legacy_snapshot(cls):
        from . import service

        cls.backup = cls.take_snapshot()
        cls.manifest = service.verify_bundle(cls.backup["bundle"], cls.backup["manifest_sha256"])
        print(
            "RECOVERY_BASELINE "
            + json.dumps(
                {
                    "tables": cls.backup["tables"],
                    "filesystem_objects": cls.backup["assets"],
                    "media_owner_references": len(cls.manifest["references"]),
                    "rows": {
                        name: cls.manifest["baseline"]["tables"][name]["rows"]
                        for name in (
                            "casework_case",
                            "casework_caseevidence",
                            "casework_answerrevision",
                            "case_attachments_caseattachment",
                            "answer_media_privateanswerrelease",
                        )
                    },
                },
                sort_keys=True,
            ),
            flush=True,
        )

    @classmethod
    def take_snapshot(cls):
        return cls.service.snapshot(
            scratch=cls.root,
            storage=cls.storage,
            pg_bin=PG_BIN,
            synthetic_fixtures_only=True,
            offline=True,
        )

    def restore(self, backup=None):
        backup = backup or self.backup
        return self.service.restore(
            bundle=backup["bundle"],
            expected_manifest_sha256=backup["manifest_sha256"],
            scratch=self.root,
            pg_bin=PG_BIN,
            synthetic_fixtures_only=True,
            offline=True,
        )

    def databases(self):
        with self.service.connect() as db:
            return db.execute("SELECT oid,datname FROM pg_database ORDER BY oid").fetchall()

    def assert_source_unchanged(self):
        with self.service.connect() as db:
            self.assertEqual(self.service.baseline(db), self.manifest["baseline"])
        for item in self.manifest["references"]:
            if item["backend"] == self.service.BACKEND:
                self.storage.get(self.service.original(item))

    def test_01_complete_restore_and_reopened_service_permissions(self):
        restored = self.restore()
        self.assertEqual(restored["state"], "READY")
        self.assertNotEqual(restored["database"], os.environ["PGDATABASE"])
        env = os.environ.copy()
        env.update(
            PGDATABASE=restored["database"],
            PGTESTDATABASE="test_" + restored["database"],
            RECOVERY_PRIVATE_ROOT=restored["private_root"],
        )
        # Tokens and expected bytes go through stdin, never into a manifest/CLI/process listing.
        fixture = {
            "receipt": self.receipt,
            "other": self.other,
            "attachment": self.attachment,
            "attachment_hex": self.attachment_raw.hex(),
        }
        completed = subprocess.run(
            [sys.executable, "-m", "apps.platform_recovery.verify_fixture"],
            input=json.dumps(fixture, default=str),
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("RESTORED_SERVICE_CHECKS_PASS", completed.stdout)
        self.assert_source_unchanged()
        with self.assertRaisesRegex(self.service.RecoveryError, "rollback_target_ineligible"):
            self.service.rollback(
                target=restored["target"], synthetic_fixtures_only=True, offline=True
            )

    def test_02_failure_each_restore_boundary_rolls_back_only_created_database(self):
        for fail_at in (
            "database_created",
            "assets_restored",
            "pre-data_restored",
            "data_restored",
            "schema_restored",
            "verified",
        ):
            with self.subTest(stage=fail_at):
                before = self.databases()

                def fail(stage):
                    if stage == fail_at:
                        raise OSError("synthetic interrupted restore")

                with patch.object(self.service, "checkpoint", side_effect=fail):
                    with self.assertRaisesRegex(self.service.RecoveryError, "target_quarantined"):
                        self.restore()
                self.assertEqual(self.databases(), before)
                self.assert_source_unchanged()
        # The same verified bundle recovers after all injected failures.
        self.assertEqual(self.restore()["state"], "READY")

    def copied_bundle(self):
        import shutil

        result = dict(self.backup)
        directory = Path(tempfile.mkdtemp(prefix="copy-", dir=self.root)) / "bundle"
        shutil.copytree(self.backup["bundle"], directory)
        result["bundle"] = str(directory)
        return result

    def test_03_missing_corrupt_dump_and_manifest_fail_before_target_creation(self):
        for damage in ("missing", "corrupt", "dump", "manifest", "incomplete"):
            with self.subTest(damage=damage):
                backup = self.copied_bundle()
                path = Path(backup["bundle"])
                blob = next((path / "objects").iterdir())
                if damage == "missing":
                    blob.unlink()
                elif damage == "corrupt":
                    blob.write_bytes(b"corrupted synthetic bytes")
                elif damage == "incomplete":
                    (path / "COMPLETE").unlink()
                else:
                    (path / ("database.dump" if damage == "dump" else "manifest.json")).write_bytes(
                        b"x"
                    )
                before = self.databases()
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    self.restore(backup)
                self.assertEqual(self.databases(), before)
        self.assert_source_unchanged()

    def test_04_snapshot_missing_and_corrupt_live_file_preserves_original_and_fails(self):
        path = next((self.storage.root / "objects").iterdir())
        raw = path.read_bytes()
        hidden = path.with_suffix(".saved")
        path.rename(hidden)
        try:
            with self.assertRaises((ValueError, RuntimeError, OSError)):
                self.take_snapshot()
            path.write_bytes(b"synthetic damaged original")
            path.chmod(0o400)
            try:
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    self.take_snapshot()
                self.assertEqual(path.read_bytes(), b"synthetic damaged original")
                self.assertEqual(hidden.read_bytes(), raw)
            finally:
                path.unlink()
        finally:
            hidden.rename(path)
        self.assert_source_unchanged()

    def test_05_snapshot_failure_never_publishes_complete_bundle(self):
        before = set(self.root.iterdir())
        with patch.object(
            self.service.PostgresTools, "run", side_effect=self.service.RecoveryError("disk_full")
        ):
            with self.assertRaises(self.service.RecoveryError):
                self.take_snapshot()
        created = set(self.root.iterdir()) - before
        self.assertEqual(len(created), 1)
        self.assertFalse((created.pop() / "COMPLETE").exists())
        self.assert_source_unchanged()

    def test_06_freeze_blocks_concurrent_database_mutation(self):
        blocked = []

        def attempt(stage):
            if stage == "frozen":
                import psycopg

                with self.service.connect() as writer:
                    writer.execute("SET lock_timeout='100ms'")
                    try:
                        writer.execute("UPDATE casework_case SET revision=revision")
                    except psycopg.errors.LockNotAvailable:
                        blocked.append(True)

        with patch.object(self.service, "checkpoint", side_effect=attempt):
            self.take_snapshot()
        self.assertEqual(blocked, [True])
        self.assert_source_unchanged()

    def test_07_symlinks_extra_files_and_unpinned_bundle_denied(self):
        backup = self.copied_bundle()
        blob = next((Path(backup["bundle"]) / "objects").iterdir())
        blob.unlink()
        blob.symlink_to(next((self.storage.root / "objects").iterdir()))
        with self.assertRaises(OSError):
            self.restore(backup)
        with self.assertRaises(self.service.RecoveryError):
            self.service.verify_bundle(self.backup["bundle"], "0" * 64)
        backup = self.copied_bundle()
        (Path(backup["bundle"]) / "objects" / "extra").write_bytes(b"extra")
        with self.assertRaisesRegex(self.service.RecoveryError, "inventory_mismatch"):
            self.restore(backup)

    def test_08_rollback_pending_if_consumer_connected_then_retry(self):
        consumers = []
        observed = []

        def fail(stage):
            if stage == "database_created":
                candidates = sorted(
                    self.root.glob("restore-*/journal.json"), key=lambda p: p.stat().st_mtime_ns
                )
                path = candidates[-1]
                state = json.loads(path.read_text())
                observed.append(path.parent)
                consumers.append(self.service.connect(state["database"]))
                raise OSError("synthetic interruption")

        before = self.databases()
        try:
            with patch.object(self.service, "checkpoint", side_effect=fail):
                with self.assertRaisesRegex(self.service.RecoveryError, "rollback_pending"):
                    self.restore()
            self.assertEqual(len(self.databases()), len(before) + 1)
        finally:
            for consumer in consumers:
                consumer.close()
        result = self.service.rollback(
            target=observed[0], synthetic_fixtures_only=True, offline=True
        )
        self.assertEqual(result["state"], "ROLLED_BACK_FILES_PRESERVED")
        self.assertEqual(self.databases(), before)
        self.service.rollback(target=observed[0], synthetic_fixtures_only=True, offline=True)
        self.assert_source_unchanged()

    def test_09_wrong_rollback_identity_is_not_dropped(self):
        from psycopg import sql

        target = Path(tempfile.mkdtemp(prefix="restore-", dir=self.root))
        name = "wave7_synthetic_restore_" + "f" * 24
        with self.service.connect() as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        self.service.journal(
            target,
            {
                "format": self.service.FORMAT,
                "database": name,
                "oid": 0,
                "nonce": "not-owned",
                "state": "RESTORING",
            },
        )
        before = self.databases()
        with self.assertRaisesRegex(self.service.RecoveryError, "rollback_identity_mismatch"):
            self.service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
        self.assertEqual(self.databases(), before)
        # This test's owned decoy is left to the disposable cluster cleanup.

    def test_10_hard_process_crash_is_quarantined_then_recovered(self):
        before = self.databases()
        paths = set(self.root.glob("restore-*"))
        payload = {
            "bundle": self.backup["bundle"],
            "expected_manifest_sha256": self.backup["manifest_sha256"],
            "scratch": str(self.root),
            "pg_bin": PG_BIN,
            "synthetic_fixtures_only": True,
            "offline": True,
        }
        script = """
import django, json, os, sys
django.setup()
from apps.platform_recovery import service
service.checkpoint = lambda stage: os._exit(73) if stage == 'data_restored' else None
service.restore(**json.load(sys.stdin))
"""
        child = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        self.assertEqual(child.returncode, 73, child.stderr)
        targets = set(self.root.glob("restore-*")) - paths
        self.assertEqual(len(targets), 1)
        target = targets.pop()
        self.assertEqual(json.loads((target / "journal.json").read_text())["state"], "RESTORING")
        self.assertTrue(list((target / "private" / "objects").iterdir()))
        self.service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
        self.assertEqual(self.databases(), before)
        self.assertTrue(list((target / "private" / "objects").iterdir()))
        self.assert_source_unchanged()

    def test_11_schema_tampering_is_detected_and_rolled_back(self):
        observed = []

        def alter(stage):
            if stage == "schema_restored":
                paths = sorted(
                    self.root.glob("restore-*/journal.json"), key=lambda p: p.stat().st_mtime_ns
                )
                state = json.loads(paths[-1].read_text())
                with self.service.connect(state["database"]) as db:
                    db.execute(
                        "ALTER TABLE wave7_synthetic_ownership DISABLE TRIGGER wave7_ownership_immutable"
                    )
                observed.append(True)

        before = self.databases()
        with patch.object(self.service, "checkpoint", side_effect=alter):
            with self.assertRaisesRegex(self.service.RecoveryError, "restored_schema_mismatch"):
                self.restore()
        self.assertEqual(observed, [True])
        self.assertEqual(self.databases(), before)

    def test_12_preexisting_database_collision_never_adopted(self):
        from psycopg import sql

        name = "wave7_synthetic_restore_" + "e" * 24
        with self.service.connect() as db:
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        before = self.databases()
        with patch.object(self.service.secrets, "token_hex", return_value="e" * 24):
            with self.assertRaises(self.service.RecoveryError):
                self.restore()
        self.assertEqual(self.databases(), before)
        with self.service.connect(name) as empty:
            with self.assertRaisesRegex(self.service.RecoveryError, "required_schema_missing"):
                self.service.baseline(empty)

    def test_13_file_write_failure_preserves_partial_target_and_retry(self):
        from apps.private_media.filesystem import FileSystemStorage

        before = self.databases()
        paths = set(self.root.glob("restore-*"))
        write = FileSystemStorage._write
        count = []

        def fail_second(store, *args):
            count.append(True)
            if len(count) == 2:
                raise OSError("synthetic disk full")
            return write(store, *args)

        with patch.object(FileSystemStorage, "_write", fail_second):
            with self.assertRaises(self.service.RecoveryError):
                self.restore()
        target = (set(self.root.glob("restore-*")) - paths).pop()
        self.assertEqual(len(list((target / "private" / "objects").iterdir())), 1)
        self.assertEqual(self.databases(), before)
        self.assertEqual(self.restore()["state"], "READY")
        self.assert_source_unchanged()

    def test_14_row_baseline_detects_cross_case_attachment_corruption(self):
        def alter(stage):
            if stage == "data_restored":
                paths = sorted(
                    self.root.glob("restore-*/journal.json"), key=lambda p: p.stat().st_mtime_ns
                )
                state = json.loads(paths[-1].read_text())
                with self.service.connect(state["database"]) as db:
                    db.execute(
                        "UPDATE case_attachments_caseattachment SET case_id=%s",
                        [self.other["case_id"]],
                    )

        before = self.databases()
        with patch.object(self.service, "checkpoint", side_effect=alter):
            with self.assertRaisesRegex(self.service.RecoveryError, "restored_baseline_mismatch"):
                self.restore()
        self.assertEqual(self.databases(), before)
        self.assert_source_unchanged()

    def test_15_owner_registry_change_fails_closed(self):
        with patch.dict(self.service.OWNERS, {"NEW_OWNER": ("casework", "Case")}):
            with self.assertRaisesRegex(self.service.RecoveryError, "media_owner_registry_changed"):
                self.take_snapshot()

    def test_16_fresh_independent_cluster_restore(self):
        fixture = {
            "receipt": self.receipt,
            "other": self.other,
            "attachment": self.attachment,
            "attachment_hex": self.attachment_raw.hex(),
        }
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "infra.dev.with_casework_postgres",
                "--pg-bin",
                PG_BIN,
                "--major",
                str(self.manifest["postgres_major"]),
                "--settings",
                self.service.V10_TEST_SETTINGS,
                "--",
                sys.executable,
                "-m",
                "apps.platform_recovery.verify_fixture",
                "--restore-bundle",
                self.backup["bundle"],
                "--manifest-sha256",
                self.backup["manifest_sha256"],
                "--scratch",
                str(self.root),
                "--pg-bin",
                PG_BIN,
            ],
            input=json.dumps(fixture, default=str),
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("RESTORED_SERVICE_CHECKS_PASS", completed.stdout)
        self.assert_source_unchanged()

    def test_17_nondefault_database_policy_fails_closed(self):
        from psycopg import sql

        with self.service.connect() as db:
            name = db.info.dbname
            db.execute(sql.SQL("ALTER DATABASE {} CONNECTION LIMIT 7").format(sql.Identifier(name)))
            try:
                with self.assertRaisesRegex(
                    self.service.RecoveryError, "database_policy_unsupported"
                ):
                    self.take_snapshot()
            finally:
                db.execute(
                    sql.SQL("ALTER DATABASE {} CONNECTION LIMIT -1").format(sql.Identifier(name))
                )

    def test_18_failure_journal_write_does_not_prevent_safe_database_rollback(self):
        before = self.databases()
        write_journal = self.service.journal
        calls = []

        def journal(path, state):
            calls.append(True)
            if len(calls) == 3:
                raise OSError("synthetic journal disk full")
            return write_journal(path, state)

        def fail(stage):
            if stage == "assets_restored":
                raise OSError("synthetic interruption")

        with (
            patch.object(self.service, "journal", side_effect=journal),
            patch.object(self.service, "checkpoint", side_effect=fail),
        ):
            with self.assertRaisesRegex(self.service.RecoveryError, "target_quarantined"):
                self.restore()
        self.assertEqual(self.databases(), before)
        self.assertEqual(len(calls), 4)
        self.assert_source_unchanged()

    def test_19_explicit_offline_guard_and_temporary_targets(self):
        with self.assertRaisesRegex(self.service.RecoveryError, "offline_synthetic_ack_required"):
            self.service.snapshot(
                scratch=self.root, storage=self.storage, pg_bin=PG_BIN, synthetic_fixtures_only=True
            )
        with self.assertRaises(self.service.RecoveryError):
            self.service.safe_directory(Path.cwd())

    def test_20_failed_ready_publication_records_failure_and_rolls_back(self):
        before = self.databases()
        paths = set(self.root.glob("restore-*"))
        write_journal = self.service.journal
        states = []

        def fail_ready(path, state):
            states.append(state["state"])
            if state["state"] == "READY":
                raise OSError("synthetic READY publication failure")
            return write_journal(path, state)

        with patch.object(self.service, "journal", side_effect=fail_ready):
            with self.assertRaisesRegex(self.service.RecoveryError, "target_quarantined"):
                self.restore()
        target = (set(self.root.glob("restore-*")) - paths).pop()
        saved = json.loads((target / "journal.json").read_text())
        self.assertEqual(
            states[-3:], ["READY", "FAILED_READY_PUBLICATION", "ROLLED_BACK_FILES_PRESERVED"]
        )
        self.assertEqual(saved["state"], "ROLLED_BACK_FILES_PRESERVED")
        self.assertEqual(saved["failure_code"], "OSError")
        self.assertEqual(self.databases(), before)
        self.assertTrue(list((target / "private" / "objects").iterdir()))
        self.service.verify_bundle(self.backup["bundle"], self.backup["manifest_sha256"])
        self.assert_source_unchanged()

    def test_21_persistent_ready_journal_failure_keeps_nonready_identity(self):
        for replaced in (False, True):
            with self.subTest(ready_already_replaced=replaced):
                before = self.databases()
                paths = set(self.root.glob("restore-*"))
                write_journal = self.service.journal
                failing = False

                def fail_from_ready(path, state):
                    nonlocal failing
                    if state["state"] == "READY":
                        if replaced:
                            write_journal(path, state)
                        failing = True
                    if failing:
                        raise OSError("synthetic persistent journal failure")
                    return write_journal(path, state)

                with patch.object(self.service, "journal", side_effect=fail_from_ready):
                    with self.assertRaisesRegex(self.service.RecoveryError, "rollback_pending"):
                        self.restore()
                target = (set(self.root.glob("restore-*")) - paths).pop()
                saved = json.loads((target / "journal.json").read_text())
                self.assertEqual(saved["state"], "FAILED_READY_PUBLICATION")
                # DROP used the durable recorded OID/nonce, but its completion
                # journal failed. Retry reconciles this without adopting a DB.
                self.assertEqual(self.databases(), before)
                result = self.service.rollback(
                    target=target, synthetic_fixtures_only=True, offline=True
                )
                self.assertEqual(result["state"], "ROLLED_BACK_FILES_PRESERVED")
                self.assertTrue(list((target / "private" / "objects").iterdir()))
                self.service.verify_bundle(self.backup["bundle"], self.backup["manifest_sha256"])
                self.assert_source_unchanged()

    def test_22_failed_ready_directory_sync_preserves_target_for_safe_retry(self):
        before = self.databases()
        paths = set(self.root.glob("restore-*"))
        sync = self.service.sync_directory
        failing = False

        def fail_after_ready_replace(path):
            nonlocal failing
            record = path / "journal.json"
            if record.exists() and json.loads(record.read_text())["state"] == "READY":
                failing = True
            if failing:
                raise OSError("synthetic persistent directory fsync failure")
            return sync(path)

        with patch.object(self.service, "sync_directory", side_effect=fail_after_ready_replace):
            with self.assertRaisesRegex(self.service.RecoveryError, "rollback_pending"):
                self.restore()
        target = (set(self.root.glob("restore-*")) - paths).pop()
        saved = json.loads((target / "journal.json").read_text())
        self.assertEqual(saved["state"], "FAILED_READY_PUBLICATION")
        self.assertIn((saved["oid"], saved["database"]), self.databases())
        self.assertEqual(len(self.databases()), len(before) + 1)
        result = self.service.rollback(target=target, synthetic_fixtures_only=True, offline=True)
        self.assertEqual(result["state"], "ROLLED_BACK_FILES_PRESERVED")
        self.assertEqual(self.databases(), before)
        self.service.verify_bundle(self.backup["bundle"], self.backup["manifest_sha256"])
        self.assert_source_unchanged()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", required=True)
    args, remaining = parser.parse_known_args()
    PG_BIN = args.pg_bin
    setup()
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
