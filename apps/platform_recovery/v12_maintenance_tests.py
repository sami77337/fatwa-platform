"""P0 admission regressions; real owned PostgreSQL, no external SQL guarantee."""

import threading
from contextvars import copy_context
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.case_attachments import storage_bindings
from apps.casework_web.models import ThrottleBucket
from tests.casework import test_v11_maintenance as fixtures

from . import admission, maintenance, service
from .integration import MaintenanceUnavailable, mutation_scope, mutation_service


@override_settings(FATWA_RECOVERY_MAINTENANCE_REQUIRED=False)
class AdmissionP0Tests(TransactionTestCase):
    setUp = fixtures.MaintenanceIntegrationTests.setUp
    freeze = fixtures.MaintenanceIntegrationTests.freeze
    resume = fixtures.MaintenanceIntegrationTests.resume

    def write(self, key="v12-synthetic"):
        ThrottleBucket.objects.create(key=key, window=1, requests=1)

    def test_unclosed_manual_transaction_on_normal_and_exception_exit_is_rolled_back(self):
        for error in (False, True):
            called = []
            with self.subTest(error=error):
                with self.assertRaisesMessage(MaintenanceUnavailable, "unclosed_transaction"):
                    with mutation_scope():
                        connection.set_autocommit(False)
                        self.write()
                        # Model a caller which stranded a pending callback.
                        connection.run_on_commit.append((set(), lambda: called.append(True), False))
                        if error:
                            raise ValueError("synthetic-domain-error")
                self.assertEqual(called, [])
                self.assertEqual(connection.run_on_commit, [])
                self.assertEqual(ThrottleBucket.objects.count(), 0)
                state = self.freeze()
                self.resume(state)

    def test_leaked_atomic_is_closed_before_permission_release(self):
        block = transaction.atomic()
        with self.assertRaisesMessage(MaintenanceUnavailable, "unclosed_transaction"):
            with mutation_scope():
                block.__enter__()
                raw = connection.connection
                self.write()
                transaction.on_commit(lambda: self.fail("uncommitted callback executed"))
        self.assertTrue(raw.closed)
        block.__exit__(None, None, None)
        self.assertEqual(ThrottleBucket.objects.count(), 0)
        self.freeze()

    def test_low_level_guard_also_rejects_outer_atomic_and_aborts_raw_begin(self):
        with transaction.atomic():
            with self.assertRaisesMessage(service.RecoveryError, "outer_boundary"):
                with maintenance.mutation_guard(root=self.control, synthetic_fixtures_only=True):
                    self.fail("must reject before the writer")
        with self.assertRaisesMessage(service.RecoveryError, "unclosed_transaction"):
            with maintenance.mutation_guard(root=self.control, synthetic_fixtures_only=True):
                with connection.cursor() as cursor:
                    cursor.execute("BEGIN")
                self.write()
        self.assertEqual(ThrottleBucket.objects.count(), 0)
        self.freeze()

    def test_caller_owned_raw_transaction_is_refused_without_rolling_it_back(self):
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
        try:
            with self.assertRaisesMessage(MaintenanceUnavailable, "outer_boundary"):
                with mutation_scope():
                    self.fail("caller boundary must be outside admission")
            self.assertEqual(connection.connection.info.transaction_status.name, "INTRANS")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK")

    def test_all_commit_callbacks_finish_before_freeze_and_resume_is_explicit(self):
        started, release = threading.Event(), threading.Event()
        failures, observed = [], []

        def writer():
            try:
                with mutation_scope(), transaction.atomic():
                    self.write()

                    def after():
                        started.set()
                        if not release.wait(10):
                            raise AssertionError("callback did not receive release")
                        with mutation_scope(), transaction.atomic():
                            self.write("v12-nested-callback")
                            transaction.on_commit(lambda: observed.append("nested"))

                    transaction.on_commit(after)
                    transaction.on_commit(lambda: observed.append("last"))
            except BaseException as exc:
                failures.append(exc)
            finally:
                connections.close_all()

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            self.assertTrue(started.wait(10))
            state = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
            self.assertEqual(state["phase"], "DRAINING")
            with self.assertRaises(MaintenanceUnavailable), mutation_scope():
                self.fail("new writer admitted")
            with self.assertRaises(service.RecoveryError):
                self.resume(state)
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(observed, ["nested", "last"])
        self.assertEqual(ThrottleBucket.objects.count(), 2)
        self.assertEqual(maintenance.status(root=self.control)["phase"], "DRAINING")
        frozen = self.freeze()
        with self.assertRaisesMessage(service.RecoveryError, "explicit_resume"):
            maintenance.resume(
                root=self.control,
                expected_generation=frozen["generation"],
                synthetic_fixtures_only=True,
            )
        self.resume(frozen)
        with self.assertRaisesMessage(service.RecoveryError, "generation_mismatch"):
            self.resume(frozen)

    def test_callback_failure_preserves_committed_work_and_domain_error(self):
        def fail():
            raise ValueError("synthetic-callback-failed")

        with self.assertRaisesMessage(ValueError, "synthetic-callback-failed"):
            with mutation_scope(), transaction.atomic():
                self.write()
                transaction.on_commit(fail)
        self.assertEqual(ThrottleBucket.objects.count(), 1)
        self.freeze()

    def test_callback_leaked_transaction_aborts_before_freeze(self):
        def leak():
            connection.set_autocommit(False)
            self.write("v12-leaked-callback")
            raise ValueError("synthetic-callback-failed")

        with self.assertRaisesMessage(MaintenanceUnavailable, "unclosed_transaction"):
            with mutation_scope(), transaction.atomic():
                self.write()
                transaction.on_commit(leak)
        self.assertEqual(
            list(ThrottleBucket.objects.values_list("key", flat=True)), ["v12-synthetic"]
        )
        self.freeze()

    def test_gc_conversion_and_storage_cannot_start_frozen(self):
        original = self.storage.put(self.media)
        self.freeze()
        with patch.object(self.storage, "_collect_orphans") as gc:
            with self.assertRaises(MaintenanceUnavailable):
                self.storage.collect_orphans(lambda _: False, dry_run=False)
            gc.assert_not_called()
        with patch.object(storage_bindings.cases, "_guard") as domain:
            with self.assertRaises(MaintenanceUnavailable):
                storage_bindings.migrate_original(
                    owner_kind="ATTACHMENT",
                    owner_id="synthetic",
                    case_id="synthetic",
                    target_storage=self.storage,
                    subject_id="synthetic",
                    provider=None,
                )
            domain.assert_not_called()
        with self.assertRaises(MaintenanceUnavailable):
            self.storage.restore(original, self.media.raw)
        self.assertEqual(self.storage.get(original), self.media.raw)

    def test_management_hook_denies_bypasses_even_when_admitted(self):
        for command in (
            "flush",
            "loaddata",
            "clearsessions",
            "dbshell",
            "shell",
            "test",
            "unknown",
        ):
            with self.subTest(command=command), mutation_scope():
                with patch("django.core.management.call_command") as run:
                    with self.assertRaisesMessage(MaintenanceUnavailable, "command_unsupported"):
                        admission.run_management_command(command)
                    run.assert_not_called()
        admission.run_management_command("check", verbosity=0)
        self.freeze()
        with patch("django.core.management.call_command") as run:
            with self.assertRaises(MaintenanceUnavailable):
                admission.run_management_command("migrate")
            run.assert_not_called()

    def test_generator_and_coroutine_cannot_escape_decorator(self):
        ran = []

        @mutation_service
        def lazy():
            ran.append(True)
            yield 1

        @mutation_service
        async def future():
            ran.append(True)

        for call in (lazy, future):
            with self.assertRaisesMessage(MaintenanceUnavailable, "deferred_work"):
                call()
        self.assertEqual(ran, [])
        self.freeze()

    def test_uncertain_cleanup_poison_prevents_freeze_resume_and_future_work(self):
        with patch.object(admission, "abort_unfinished", side_effect=OSError("synthetic-close")):
            with self.assertRaisesMessage(MaintenanceUnavailable, "cleanup_failed"):
                with mutation_scope():
                    pass
        self.assertTrue((self.control / "unsafe-transaction").is_file())
        with self.assertRaisesMessage(service.RecoveryError, "cleanup_unproven"):
            self.freeze()
        with self.assertRaises(MaintenanceUnavailable), mutation_scope():
            self.fail("poisoned control admitted work")
        with self.assertRaisesMessage(service.RecoveryError, "cleanup_unproven"):
            maintenance.resume(
                root=self.control,
                expected_generation="synthetic",
                confirmed=True,
                synthetic_fixtures_only=True,
            )

    def test_rollback_ack_failure_closes_connection_and_blocks_snapshot(self):
        raw = connection.connection
        with patch.object(type(raw), "rollback", side_effect=OSError("synthetic-rollback")):
            with self.assertRaisesMessage(MaintenanceUnavailable, "cleanup_failed"):
                with mutation_scope():
                    connection.set_autocommit(False)
                    self.write()
        self.assertTrue(raw.closed)
        self.assertEqual(ThrottleBucket.objects.count(), 0)
        with self.assertRaisesMessage(service.RecoveryError, "cleanup_unproven"):
            self.freeze()

    def test_drain_waits_for_rollback_acknowledgement(self):
        started, release = threading.Event(), threading.Event()
        leaked, failures = {}, []
        driver = type(connection.connection)
        rollback = driver.rollback

        def slow_rollback(raw):
            if raw is leaked.get("connection"):
                started.set()
                if not release.wait(10):
                    raise AssertionError("rollback release timed out")
            return rollback(raw)

        def writer():
            try:
                with mutation_scope():
                    connection.set_autocommit(False)
                    leaked["connection"] = connection.connection
                    self.write()
            except MaintenanceUnavailable as exc:
                failures.append(str(exc))
            finally:
                connections.close_all()

        with patch.object(driver, "rollback", slow_rollback):
            thread = threading.Thread(target=writer)
            thread.start()
            try:
                self.assertTrue(started.wait(10))
                state = maintenance.enter(root=self.control, synthetic_fixtures_only=True)
                self.assertEqual(state["phase"], "DRAINING")
                self.assertFalse(leaked["connection"].closed)
                self.assertEqual(ThrottleBucket.objects.count(), 0)
            finally:
                release.set()
                thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, ["maintenance_unclosed_transaction"])
        self.assertTrue(leaked["connection"].closed)
        self.assertEqual(ThrottleBucket.objects.count(), 0)
        self.freeze()

    def test_expired_copied_context_cannot_reenter_frozen(self):
        with mutation_scope():
            copied = copy_context()
        self.freeze()
        with self.assertRaises(MaintenanceUnavailable):
            copied.run(mutation_service(lambda: self.fail("stale lease admitted work")))

    def test_offline_restore_exception_is_write_only_and_operations_are_validated(self):
        from . import integration
        from .leases import Lease, execution

        with mutation_scope():
            with self.assertRaisesMessage(MaintenanceUnavailable, "operation_unsupported"):
                with mutation_scope(operation="UNKNOWN"):
                    self.fail("invalid operation")
        self.freeze()
        # Isolate the scope policy without manufacturing a restore DB/permission.
        with patch.object(integration, "_RESTORE_FILES") as marker:
            marker.get.return_value = Lease(str(self.storage.root), execution())
            with self.assertRaisesMessage(MaintenanceUnavailable, "restore_write_only"):
                with integration.storage_scope(self.storage.root, operation="GC"):
                    self.fail("restore scope cannot collect files")

    def test_snapshot_lease_blocks_resume_and_preserves_generation(self):
        state = self.freeze()
        with maintenance.frozen(root=self.control, storage=self.storage):
            with self.assertRaisesMessage(service.RecoveryError, "maintenance_busy"):
                self.resume(state)
            with self.assertRaises(MaintenanceUnavailable), mutation_scope():
                self.fail("snapshot admitted a writer")
        self.assertEqual(maintenance.status(root=self.control)["generation"], state["generation"])
        self.assertEqual(self.freeze()["generation"], state["generation"])
        self.resume(state)
