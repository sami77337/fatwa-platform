"""Owned temporary directories; no cloud, public paths, real media or production settings."""

import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .filesystem import BACKEND, FileSystemStorage
from .storage import InlineDatabaseStorage, read_original
from .validation import MediaValidationError, validate


class FileSystemTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fatwa-private-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"FATWA_PRODUCTION": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = FileSystemStorage(
            self.base / "private-originals", synthetic_fixtures_only=True
        )
        self.media = validate(b"synthetic original\n", "sample.txt", "text/plain")

    def old(self, original):
        path = self.store.root / "objects" / original.key
        os.utime(path, (time.time() - 90000, time.time() - 90000))
        return path

    def test_durable_private_original_idempotent_and_legacy_resolver(self):
        original = self.store.put(self.media)
        self.assertEqual(original.backend, BACKEND)
        self.assertIsNone(original.inline)
        path = self.store.root / "objects" / original.key
        inode, mtime = path.stat().st_ino, path.stat().st_mtime_ns
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
        restarted = FileSystemStorage(self.store.root, synthetic_fixtures_only=True)
        self.assertEqual(restarted.get(original), self.media.raw)
        self.assertEqual(restarted.put(self.media), original)
        self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns), (inode, mtime))
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=restarted):
            self.assertEqual(read_original(original), self.media.raw)
            legacy = InlineDatabaseStorage().put(self.media)
            self.assertEqual(read_original(legacy), self.media.raw)

    def test_closed_root_traversal_symlinks_public_directory_and_permissions(self):
        for path, ack in (
            (self.base / "closed", False),
            (Path("relative"), True),
            (self.base / "media", True),
            (self.base / ".." / "escape", True),
        ):
            with self.subTest(path=path), self.assertRaises(MediaValidationError):
                FileSystemStorage(path, synthetic_fixtures_only=ack)
        with (
            patch.dict(os.environ, {"FATWA_PRODUCTION": "1"}),
            self.assertRaises(MediaValidationError),
        ):
            FileSystemStorage(self.base / "production", synthetic_fixtures_only=True)
        linked = self.base / "linked"
        linked.symlink_to(self.store.root, target_is_directory=True)
        with self.assertRaises(MediaValidationError):
            FileSystemStorage(linked, synthetic_fixtures_only=True)
        open_directory = self.base / "open"
        open_directory.mkdir(mode=0o755)
        open_directory.chmod(0o755)
        with self.assertRaises(MediaValidationError):
            FileSystemStorage(open_directory, synthetic_fixtures_only=True)
        occupied = self.base / "occupied"
        occupied.mkdir(mode=0o700)
        (occupied / "do-not-touch").write_bytes(b"unrelated")
        with self.assertRaises(MediaValidationError):
            FileSystemStorage(occupied, synthetic_fixtures_only=True)
        self.assertEqual((occupied / "do-not-touch").read_bytes(), b"unrelated")

    def test_invalid_pointers_corruption_and_symlink_are_never_read_or_overwritten(self):
        original = self.store.put(self.media)
        for changed in (
            replace(original, key="../outside"),
            replace(original, backend="other"),
            replace(original, size=original.size + 1),
            replace(original, inline=b"alternate"),
        ):
            with self.assertRaises(MediaValidationError):
                self.store.get(changed)
        path = self.store.root / "objects" / original.key
        path.chmod(0o600)
        path.write_bytes(b"corrupt")
        path.chmod(0o400)
        with self.assertRaises(MediaValidationError):
            self.store.get(original)
        with self.assertRaises(MediaValidationError):
            self.store.put(self.media)
        self.assertEqual(path.read_bytes(), b"corrupt")
        path.unlink()
        outside = self.base / "outside"
        outside.write_bytes(self.media.raw)
        path.symlink_to(outside)
        with self.assertRaises(MediaValidationError):
            self.store.get(original)
        with self.assertRaises(MediaValidationError):
            self.store.restore(original, self.media.raw, recover_corrupt=True)
        self.assertEqual(outside.read_bytes(), self.media.raw)

    def test_partial_write_and_fsync_failures_never_publish_partial_original(self):
        with patch(
            "apps.private_media.filesystem.os.write", side_effect=OSError("synthetic disk full")
        ):
            with self.assertRaises(MediaValidationError):
                self.store.put(self.media)
        self.assertEqual(list((self.store.root / "objects").iterdir()), [])
        original_fsync = os.fsync

        def fail_file_sync(descriptor):
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("synthetic fsync failure")
            return original_fsync(descriptor)

        with patch("apps.private_media.filesystem.os.fsync", side_effect=fail_file_sync):
            with self.assertRaises(MediaValidationError):
                self.store.put(self.media)
        self.assertEqual(list((self.store.root / "objects").iterdir()), [])
        original = self.store.put(self.media)
        self.assertEqual(self.store.get(original), self.media.raw)

    def test_final_directory_sync_failure_is_recoverable_without_replacing_original(self):
        original_fsync = os.fsync

        def fail_directory_sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("synthetic directory sync failure")
            return original_fsync(descriptor)

        with patch("apps.private_media.filesystem.os.fsync", side_effect=fail_directory_sync):
            with self.assertRaises(MediaValidationError):
                self.store.put(self.media)
        paths = list((self.store.root / "objects").glob("*.blob"))
        self.assertEqual(len(paths), 1)
        before = paths[0].stat().st_ino
        original = self.store.put(self.media)
        self.assertEqual(paths[0].stat().st_ino, before)
        self.assertEqual(self.store.get(original), self.media.raw)

    def test_exact_backup_restores_missing_and_quarantines_explicit_corruption(self):
        original = self.store.put(self.media)
        path = self.store.root / "objects" / original.key
        path.unlink()
        with self.assertRaises(MediaValidationError):
            self.store.restore(original, b"wrong backup")
        self.assertFalse(path.exists())
        self.assertEqual(
            self.store.restore(original, self.media.raw), {"restored": True, "quarantined": False}
        )
        path.chmod(0o600)
        path.write_bytes(b"damaged synthetic original")
        path.chmod(0o400)
        with self.assertRaises(MediaValidationError):
            self.store.restore(original, self.media.raw)
        result = self.store.restore(original, self.media.raw, recover_corrupt=True)
        self.assertEqual(result, {"restored": True, "quarantined": True})
        self.assertEqual(self.store.get(original), self.media.raw)
        quarantined = list((self.store.root / "quarantine").iterdir())
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), b"damaged synthetic original")

    def test_gc_dry_run_grace_live_refs_corrupt_unknown_and_explicit_removal(self):
        original = self.store.put(self.media)
        self.assertEqual(
            self.store.collect_orphans(lambda _: False)[0]["status"], "GRACE_PRESERVED"
        )
        path = self.old(original)
        self.assertEqual(
            self.store.collect_orphans(lambda _: True)[0]["status"], "REFERENCED_PRESERVED"
        )
        self.assertEqual(self.store.collect_orphans(lambda _: False)[0]["status"], "WOULD_REMOVE")
        self.assertTrue(path.exists())
        unknown = path.parent / "unrecognized"
        unknown.write_bytes(b"never delete")
        corrupt = path.parent / ("0" * 64 + ".blob")
        corrupt.write_bytes(b"corrupt")
        corrupt.chmod(0o400)
        report = self.store.collect_orphans(lambda _: False, dry_run=False)
        self.assertIn({"key": original.key, "status": "REMOVED"}, report)
        self.assertTrue(unknown.exists())
        self.assertTrue(corrupt.exists())
        self.assertFalse(path.exists())
        self.assertTrue((self.store.root / "locks" / (original.sha256 + ".lock")).exists())
        with self.assertRaises(MediaValidationError):
            self.store.collect_orphans(lambda _: False, grace_seconds=0, dry_run=False)

    def test_reference_callback_failure_preserves_object(self):
        original = self.store.put(self.media)
        path = self.old(original)

        def unavailable(_):
            raise RuntimeError("synthetic database unavailable")

        self.assertEqual(
            self.store.collect_orphans(unavailable, dry_run=False)[0]["status"],
            "REFERENCE_UNAVAILABLE_PRESERVED",
        )
        self.assertTrue(path.exists())

    def test_binding_lock_holds_gc_until_reference_commit_and_serializes_writers(self):
        original = self.store.put(self.media)
        path = self.old(original)
        entered, release, referenced = threading.Event(), threading.Event(), threading.Event()

        def writer():
            with self.store.binding_lock(original.sha256):
                self.store.put(self.media)
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test release timed out")
                referenced.set()  # Stand-in for outer DB commit while lock remains held.

        with ThreadPoolExecutor(max_workers=2) as executor:
            pending_writer = executor.submit(writer)
            self.assertTrue(entered.wait(5))
            pending_gc = executor.submit(
                self.store.collect_orphans, lambda _: referenced.is_set(), dry_run=False
            )
            time.sleep(0.08)
            self.assertFalse(pending_gc.done())
            release.set()
            pending_writer.result(timeout=5)
            self.assertEqual(pending_gc.result(timeout=5)[0]["status"], "REFERENCED_PRESERVED")
        self.assertTrue(path.exists())
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.store.put(self.media), range(4)))
        self.assertEqual(results, [original] * 4)
        self.assertEqual(len(list((self.store.root / "objects").glob("*.blob"))), 1)

    def test_cross_process_binding_lock_blocks_reference_check_until_release(self):
        original = self.store.put(self.media)
        self.old(original)
        code = """
import sys
from apps.private_media.filesystem import FileSystemStorage
store = FileSystemStorage(sys.argv[1], synthetic_fixtures_only=True)
with store.binding_lock(sys.argv[2]):
    print("locked", flush=True)
    sys.stdin.readline()
"""
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(self.store.root), original.sha256],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            called = threading.Event()

            def reference(_):
                called.set()
                return True

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.store.collect_orphans, reference, dry_run=False)
                time.sleep(0.08)
                self.assertFalse(called.is_set())
                child.communicate("release\n", timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(future.result(timeout=5)[0]["status"], "REFERENCED_PRESERVED")
            self.assertTrue(called.is_set())
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)

    def test_restore_write_failure_keeps_corrupt_backup_for_retry(self):
        original = self.store.put(self.media)
        path = self.store.root / "objects" / original.key
        path.chmod(0o600)
        path.write_bytes(b"damaged")
        path.chmod(0o400)
        with patch.object(self.store, "_write", side_effect=OSError("synthetic restore failure")):
            with self.assertRaises(MediaValidationError):
                self.store.restore(original, self.media.raw, recover_corrupt=True)
        self.assertFalse(path.exists())
        quarantined = list((self.store.root / "quarantine").iterdir())
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), b"damaged")
        self.assertEqual(
            self.store.restore(original, self.media.raw), {"restored": True, "quarantined": False}
        )
        self.assertEqual(self.store.get(original), self.media.raw)

    def test_cleanup_sync_failure_reports_uncertain_removal_and_nan_grace_is_rejected(self):
        original = self.store.put(self.media)
        path = self.old(original)
        with self.assertRaises(MediaValidationError):
            self.store.collect_orphans(lambda _: False, grace_seconds=float("nan"), dry_run=False)
        self.assertTrue(path.exists())
        with patch(
            "apps.private_media.filesystem.os.fsync",
            side_effect=OSError("synthetic directory sync failure"),
        ):
            report = self.store.collect_orphans(lambda _: False, dry_run=False)
        self.assertEqual(report[0]["status"], "REMOVED_DURABILITY_UNCONFIRMED")
        self.assertFalse(path.exists())

    def test_read_does_not_take_binding_lock_inside_owner_database_scope(self):
        original = self.store.put(self.media)
        with patch.object(
            self.store,
            "binding_lock",
            side_effect=AssertionError("read must not invert lock order"),
        ):
            self.assertEqual(self.store.get(original), self.media.raw)
