"""V11 cooperative drain/freeze boundaries on a disposable synthetic PostgreSQL DB."""

import os
import tempfile
import threading
from contextvars import copy_context
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.case_attachments import services as attachments
from apps.case_attachments.storage_bindings import binding_locks
from apps.casework import services as cases
from apps.casework.models import Case
from apps.casework_web.models import ThrottleBucket
from apps.delivery_queue import services as queue
from apps.intake_workflow.guards import require_owned_migration, synthetic_atomic
from apps.platform_recovery import maintenance, service
from apps.platform_recovery.integration import (
    MaintenanceUnavailable,
    mutation_scope,
    mutation_service,
    offline_restore_files,
    require_admission,
)
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.validation import ValidatedMedia
from apps.reference.ingest import ingest_catalog
from apps.reference.models import ReferenceWork
from apps.source_case_intake import services as sources
from apps.source_case_intake import simulators
from apps.source_case_intake.adapters import IntakeError
from apps.source_case_intake.models import SourceReceipt
from tests.casework.test_http import WEB_SETTINGS
from tests.reference.test_catalog import fixture


@override_settings(
    FATWA_RECOVERY_MAINTENANCE_REQUIRED=False,
    FATWA_SOURCE_CASE_INTAKE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
)
class MaintenanceIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v11-maintenance-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = FileSystemStorage(self.root / "private", synthetic_fixtures_only=True)
        self.control = self.root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(
            root=self.control, storage=self.storage, synthetic_fixtures_only=True
        )
        self.enabled = override_settings(
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=str(self.control),
            FATWA_PRIVATE_MEDIA_STORAGE=self.storage,
        )
        self.enabled.enable()
        self.addCleanup(self.enabled.disable)
        raw = b"small fabricated original"
        self.media = ValidatedMedia(
            raw,
            "synthetic.txt",
            "text/plain",
            sha256(raw).hexdigest(),
            len(raw),
            "TEXT",
            {"encoding": "UTF-8"},
        )

    def freeze(self):
        result = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
        self.assertEqual(result["phase"], "FROZEN")
        return result

    def resume(self, result):
        maintenance.resume(
            root=self.control,
            expected_generation=result["generation"],
            confirmed=True,
            synthetic_fixtures_only=True,
        )

    def capture(self):
        return sources.capture(
            raw=simulators.telegram(),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )

    def test_direct_service_and_queue_fastpath_block_frozen_and_resume(self):
        first = self.capture()
        self.assertEqual(SourceReceipt.objects.count(), 1)
        state = self.freeze()
        for operation in (
            self.capture,
            lambda: sources.ingest(
                raw=simulators.telegram(),
                context=simulators.context("telegram"),
                synthetic_fixtures_only=True,
            ),
            lambda: queue.claim_next(provider=None, worker_id="synthetic-worker"),
            lambda: queue.quarantine_expired_leases(),
            lambda: attachments.requester_list(token="not-a-secret", synthetic_fixtures_only=True),
        ):
            with self.subTest(operation=operation), self.assertRaises(MaintenanceUnavailable):
                operation()
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.resume(state)
        self.assertEqual(self.capture().pk, first.pk)
        with self.assertRaisesMessage(MaintenanceUnavailable, "boundary_required"):
            queue._postgres_only()  # Undecorated internal entry does not silently become a writer.
        with mutation_scope(), queue.synthetic_queue_atomic():
            self.assertIsNotNone(queue._postgres_only())

    def test_drain_holds_through_outer_commit_and_on_commit_native_service(self):
        callback_started, release = threading.Event(), threading.Event()
        failures = []

        @mutation_service
        def writer():
            with queue.synthetic_queue_atomic():
                cases.intake_case(
                    original_question="synthetic drain question",
                    source_event_id="drain-case",
                    requester_id="drain-requester",
                    idempotency_key="drain-key",
                    synthetic_fixtures_only=True,
                )

                def after_commit():
                    callback_started.set()
                    if not release.wait(10):
                        raise AssertionError("callback release timed out")
                    self.capture()  # Separate native commit still belongs to admitted work.

                transaction.on_commit(after_commit)

        def worker():
            try:
                writer()
            except BaseException as exc:
                failures.append(exc)
            finally:
                connections.close_all()

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(callback_started.wait(10))
            draining = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
            self.assertEqual(draining["phase"], "DRAINING")
            self.assertEqual(
                Case.objects.count(), 1
            )  # Outer DB commit completed; callback still holds lease.
            with self.assertRaises(MaintenanceUnavailable):
                self.capture()
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.freeze()

    def test_binding_lease_covers_gc_put_restore_and_root_binding(self):
        original = self.storage.put(self.media)
        with binding_locks(self.storage, [self.media.sha256]):
            state = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
            self.assertEqual(state["phase"], "DRAINING")
            with transaction.atomic():
                transaction.on_commit(require_admission)
        state = self.freeze()
        called = []
        for operation in (
            lambda: self.storage.put(self.media),
            lambda: self.storage.restore(original, self.media.raw),
            lambda: self.storage.collect_orphans(
                lambda item: called.append(item) or False, dry_run=False
            ),
            lambda: FileSystemStorage(self.storage.root, synthetic_fixtures_only=True),
        ):
            with self.assertRaises(MaintenanceUnavailable):
                operation()
        self.assertEqual(called, [])
        self.assertEqual(self.storage.get(original), self.media.raw)
        self.resume(state)
        self.assertEqual(self.storage.restore(original, self.media.raw)["restored"], False)
        with self.assertRaisesMessage(MaintenanceUnavailable, "storage_mismatch"):
            FileSystemStorage(self.root / "foreign", synthetic_fixtures_only=True)
        self.assertFalse((self.root / "foreign").exists())

    @override_settings(
        **{
            **WEB_SETTINGS,
            "ROOT_URLCONF": "config.campaign_urls",
            "MIDDLEWARE": [
                "apps.platform_recovery.middleware.MaintenanceGuard",
                *WEB_SETTINGS["MIDDLEWARE"],
            ],
        }
    )
    def test_topmost_http_gate_includes_get_head_throttle_and_session_writes(self):
        client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.assertEqual(client.get("/casework/").status_code, 200)
        before = list(ThrottleBucket.objects.values_list("key", "window", "requests"))
        state = self.freeze()
        for method, path in (
            ("get", "/casework/"),
            ("head", "/casework/staff/"),
            ("post", "/casework/"),
            ("get", "/casework/library/"),
        ):
            response = getattr(client, method)(path)
            self.assertEqual(response.status_code, 503)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(response.cookies, {})
        self.assertEqual(
            list(ThrottleBucket.objects.values_list("key", "window", "requests")), before
        )
        self.resume(state)
        self.assertEqual(client.get("/casework/").status_code, 200)

    def test_missing_root_and_uninitialized_control_fail_closed(self):
        for value in (None, {}, str(self.root / "absent")):
            with override_settings(FATWA_RECOVERY_MAINTENANCE_ROOT=value):
                with self.assertRaises(MaintenanceUnavailable):
                    self.capture()
                with self.assertRaises(MaintenanceUnavailable):
                    self.storage.put(self.media)
        self.assertEqual(SourceReceipt.objects.count(), 0)
        self.assertEqual(list((self.storage.root / "objects").iterdir()), [])

    def test_wave7_reference_commit_migrate_and_outer_transaction_boundaries(self):
        spec, rows = fixture()
        preview = ingest_catalog(spec, rows)
        state = self.freeze()
        self.assertTrue(
            ingest_catalog(spec, rows).dry_run
        )  # Pure read-only preview remains read-only.
        with self.assertRaises(MaintenanceUnavailable):
            ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum)
        with (
            self.assertRaises(MaintenanceUnavailable),
            synthetic_atomic(synthetic_fixtures_only=True),
        ):
            self.fail("Wave7 should be blocked")
        with self.assertRaisesMessage(CommandError, "MAINTENANCE_ADMINISTRATION_UNAVAILABLE"):
            call_command("migrate", interactive=False, verbosity=0)
        with self.assertRaises(MaintenanceUnavailable):
            require_owned_migration(None, "default")
        self.assertEqual(ReferenceWork.objects.count(), 0)
        self.resume(state)
        result = ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum)
        self.assertIsNotNone(result.edition_id)
        call_command("migrate", interactive=False, verbosity=0)
        with (
            transaction.atomic(),
            self.assertRaisesMessage(MaintenanceUnavailable, "outer_boundary"),
        ):
            self.capture()

    def test_native_capture_commit_and_domain_errors_are_preserved(self):
        with patch.object(sources, "process", side_effect=IntakeError("synthetic-failure")):
            with self.assertRaisesMessage(IntakeError, "synthetic-failure"):
                sources.ingest(
                    raw=simulators.telegram(),
                    context=simulators.context("telegram"),
                    synthetic_fixtures_only=True,
                )
        self.assertEqual(SourceReceipt.objects.count(), 1)
        self.assertEqual(Case.objects.count(), 0)
        self.freeze()  # Exception releases admission, including copied-context markers.

    def test_copied_lease_and_connection_target_change_cannot_bypass_admission(self):
        with mutation_scope():
            copied = copy_context()
            with patch.dict(connection.settings_dict, {"PORT": "1"}):
                with self.assertRaisesMessage(MaintenanceUnavailable, "database_changed"):
                    require_admission()
        self.freeze()
        with self.assertRaises(MaintenanceUnavailable):
            copied.run(self.capture)

    def test_offline_target_scope_requires_operation_identity_and_never_admits_source(self):
        target = self.root / "restore-fake"
        target.mkdir(mode=0o700)
        state = {
            "state": "RESTORING",
            "database": "wave7_synthetic_restore_" + "a" * 24,
            "nonce": "synthetic-recovery:" + "b" * 64,
            "oid": 123,
        }
        service.journal(target, state)
        with self.assertRaisesMessage(service.RecoveryError, "lease_required"):
            with offline_restore_files(target=target, state=state):
                self.fail("no operation lease")
        with (
            service.target_operation(target),
            self.assertRaisesMessage(service.RecoveryError, "identity_mismatch"),
        ):
            with offline_restore_files(target=target, state=state):
                self.fail("unproven target")
        self.assertFalse((target / "private").exists())

    def test_encrypted_restore_writes_only_proven_new_target_while_source_frozen(self):
        from apps.platform_recovery import encrypted

        pg_bin = os.environ.get("FATWA_TEST_PG_BIN")
        if not pg_bin:
            self.skipTest("FATWA_TEST_PG_BIN required for the real encrypted restore drill")
        receipt = sources.ingest(
            raw=simulators.telegram(),
            context=simulators.context("telegram"),
            synthetic_fixtures_only=True,
        )
        original = attachments.upload(
            token=receipt["token"],
            raw=self.media.raw,
            filename="synthetic.txt",
            media_type="text/plain",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        keys = tempfile.TemporaryDirectory(prefix="v11-maintenance-keys-")
        self.addCleanup(keys.cleanup)
        key = Path(keys.name) / "key"
        encrypted.generate_key(path=key, synthetic_fixtures_only=True)
        self.freeze()
        sealed = encrypted.snapshot(
            scratch=self.root,
            storage=self.storage,
            pg_bin=pg_bin,
            key_file=key,
            maintenance_root=self.control,
            synthetic_fixtures_only=True,
        )
        restored = encrypted.restore(
            bundle=sealed["bundle"],
            expected_ciphertext_sha256=sealed["ciphertext_sha256"],
            key_file=key,
            scratch=self.root,
            pg_bin=pg_bin,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(restored["state"], "READY")
        recovered = Path(restored["private_root"]) / "objects" / (original["sha256"] + ".blob")
        self.assertEqual(recovered.read_bytes(), self.media.raw)
        self.assertEqual(maintenance.status(root=self.control)["phase"], "FROZEN")
        with self.assertRaises(MaintenanceUnavailable):
            self.capture()
        with self.assertRaises(MaintenanceUnavailable):
            self.storage.restore(self.storage.put(self.media), self.media.raw)

    def test_streaming_work_is_not_run_after_scope_and_default_profile_is_compatible(self):
        from django.http import StreamingHttpResponse

        from apps.platform_recovery.middleware import MaintenanceGuard

        ran = []

        def stream():
            ran.append(True)
            yield b"synthetic"

        wrapped = MaintenanceGuard(lambda request: StreamingHttpResponse(stream()))
        self.assertEqual(wrapped(None).status_code, 503)
        self.assertEqual(ran, [])
        with override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=False):
            response = wrapped(None)
            self.assertTrue(response.streaming)
            response.close()
