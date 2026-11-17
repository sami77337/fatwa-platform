"""Synthetic PostgreSQL owner binding, conversion and immutable reference checks."""

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from dataclasses import replace
from threading import Event
from unittest.mock import patch

from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, connection, connections, transaction
from django.db.models.query import QuerySet
from django.test import TransactionTestCase, override_settings

from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.case_attachments.storage_bindings import live_references, migrate_original
from apps.casework import services as cases
from apps.casework.models import Case, CaseMediaStorageTransition
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.storage import InlineDatabaseStorage
from apps.private_media.validation import MediaValidationError

from . import services
from . import tests as answer_tests
from .models import AnswerManifest, AnswerPart, PrivateAnswerRelease
from .tests import audio_fixture


@override_settings(
    FATWA_ANSWER_MEDIA_ENABLED=True,
    FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_MEDIA_STORAGE_MIGRATION_ENABLED=True,
)
class StorageBindingTests(TransactionTestCase):
    save = answer_tests.AnswerMediaTests.save
    approve = answer_tests.AnswerMediaTests.approve
    release = answer_tests.AnswerMediaTests.release
    private = answer_tests.AnswerMediaTests.private

    def setUp(self):
        answer_tests.AnswerMediaTests.setUp(self)
        self.directory_root = tempfile.TemporaryDirectory(prefix="fatwa-v9-bindings-")
        self.addCleanup(self.directory_root.cleanup)
        self.storage = FileSystemStorage(self.directory_root.name, synthetic_fixtures_only=True)
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        configured.enable()
        self.addCleanup(configured.disable)

    def part(self):
        return AnswerPart.objects.filter(ordinal=2).latest("created_at")

    def convert(self, row, target=None, **changes):
        args = {
            **self.common,
            "owner_kind": "ANSWER_PART",
            "owner_id": row.pk,
            "target_storage": target or self.storage,
            "confirmed": True,
            "expected_sha256": row.sha256,
        }
        return migrate_original(**{**args, **changes})

    def attachment(self):
        case = cases.read_case(**self.common)
        result = attachments.upload(
            token=self.receipt["token"],
            **audio_fixture(),
            expected_revision=case["revision"],
            synthetic_fixtures_only=True,
        )
        return CaseAttachment.objects.get(pk=result["id"])

    def test_filesystem_upload_reads_and_retained_clone_preserve_external_original(self):
        self.save()
        row = self.part()
        self.assertIsNone(row.original)
        self.assertEqual(row.storage_key, row.sha256 + ".blob")
        self.assertEqual(services.raw_for_part(row), audio_fixture()["raw"])
        self.assertIsNotNone(AnswerPart.objects.get(ordinal=1).original)
        self.save(files=[], retained_part_ids=[str(row.pk)])
        retained = self.part()
        self.assertNotEqual(retained.pk, row.pk)
        self.assertIsNone(retained.original)
        self.assertEqual(retained.storage_key, row.storage_key)
        self.assertTrue(live_references(row.storage_backend, row.storage_key))

    def test_external_cross_editor_clone_preserves_pointer_without_release(self):
        answer_tests.AnswerMediaTests.test_cross_editor_copy_preserves_files_but_not_approval_or_private_release(
            self
        )
        cloned = self.part()
        self.assertIsNone(cloned.original)
        self.assertEqual(services.raw_for_part(cloned), audio_fixture()["raw"])

    def test_inline_roundtrip_preserves_approval_release_manifest_and_case_versions(self):
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=None):
            self.save()
            self.approve()
            self.release()
        row = self.part()
        # Switching configuration never strands old inline originals.
        self.assertEqual(services.raw_for_part(row), audio_fixture()["raw"])
        before = Case.objects.values().get(pk=self.receipt["case_id"])
        manifest_before = AnswerManifest.objects.values().get()
        release_before = PrivateAnswerRelease.objects.values().get()
        self.convert(row)
        row.refresh_from_db()
        self.assertIsNone(row.original)
        self.assertTrue(self.private()["package"]["approved"])
        self.convert(row, InlineDatabaseStorage())
        row.refresh_from_db()
        self.assertEqual(bytes(row.original), audio_fixture()["raw"])
        self.assertEqual(Case.objects.values().get(pk=row.manifest.answer.case_id), before)
        self.assertEqual(AnswerManifest.objects.values().get(), manifest_before)
        self.assertEqual(PrivateAnswerRelease.objects.values().get(), release_before)
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 2)
        self.assertFalse(live_references("private-filesystem-v1", row.sha256 + ".blob"))

    def test_attachment_roundtrip_preserves_evidence_and_reads(self):
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=None):
            row = self.attachment()
        evidence = row.evidence_id
        case_before = Case.objects.values().get(pk=row.case_id)
        self.convert(row, owner_kind="ATTACHMENT")
        row.refresh_from_db()
        self.assertIsNone(row.original)
        result = attachments.requester_read(
            token=self.receipt["token"], attachment_id=row.pk, synthetic_fixtures_only=True
        )
        self.assertEqual(result["raw"], audio_fixture()["raw"])
        self.assertTrue(live_references(row.storage_backend, row.storage_key))
        self.convert(row, InlineDatabaseStorage(), owner_kind="ATTACHMENT")
        row.refresh_from_db()
        self.assertEqual(row.evidence_id, evidence)
        self.assertEqual(Case.objects.values().get(pk=row.case_id), case_before)
        self.assertEqual(bytes(row.original), audio_fixture()["raw"])

    def test_failed_write_or_postwrite_authority_change_rolls_back_binding_and_audit(self):
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=None):
            self.save()
        row = self.part()
        original_put = self.storage.put

        def fail_after_write(media):
            original_put(media)
            raise MediaValidationError("synthetic_storage_failure")

        with patch.object(self.storage, "put", side_effect=fail_after_write):
            with self.assertRaises(cases.CaseConflict):
                self.convert(row)
        self.assertTrue((self.storage.root / "objects" / (row.sha256 + ".blob")).exists())
        row.refresh_from_db()
        self.assertEqual(row.storage_backend, "inline-database-v1")
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 0)

        def revoke_after_write(media):
            result = original_put(media)
            self.directory.current = replace(self.directory.current, auth_epoch="revoked-epoch")
            return result

        with patch.object(self.storage, "put", side_effect=revoke_after_write):
            with self.assertRaises(cases.CaseConflict):
                self.convert(row)
        row.refresh_from_db()
        self.assertIsNotNone(row.original)
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 0)

    def test_corrupt_external_bytes_deny_read_approval_and_reverse_conversion(self):
        self.save()
        row = self.part()
        path = self.storage.root / "objects" / row.storage_key
        path.chmod(0o600)
        path.write_bytes(b"not original")
        path.chmod(0o400)
        with self.assertRaises(cases.CaseConflict):
            services.staff_read(
                part_id=row.pk, **{k: v for k, v in self.common.items() if k != "case_id"}
            )
        with self.assertRaises(cases.CaseConflict):
            self.approve()
        with self.assertRaises(cases.CaseConflict):
            self.convert(row, InlineDatabaseStorage())
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 0)

    def test_conversion_closed_unauthorized_crosscase_and_text_part(self):
        self.save()
        row = self.part()
        for changes in (
            {"confirmed": False},
            {"subject_id": "requester-one"},
            {"expected_sha256": "0" * 64},
            {"synthetic_fixtures_only": False},
        ):
            with self.assertRaises(cases.CaseConflict):
                self.convert(row, InlineDatabaseStorage(), **changes)
        with override_settings(FATWA_MEDIA_STORAGE_MIGRATION_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.convert(row, InlineDatabaseStorage())
        with self.assertRaises(cases.CaseConflict):
            self.convert(AnswerPart.objects.get(ordinal=1))
        other = cases.intake_case(
            original_question="سؤال ثان اصطناعي",
            source_event_id="storage-other",
            requester_id="other",
            idempotency_key="storage-other",
            synthetic_fixtures_only=True,
        )
        self.directory.grant(other["public_ref"])
        with self.assertRaises(cases.CaseConflict):
            self.convert(row, InlineDatabaseStorage(), case_id=other["case_id"])
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 0)

    def test_database_rejects_unaudited_pointer_change_and_incomplete_audit(self):
        self.save()
        row = self.part()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerPart.objects.filter(pk=row.pk).update(
                original=audio_fixture()["raw"],
                storage_backend="inline-database-v1",
                storage_key=row.sha256,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseMediaStorageTransition.objects.create(
                case_id=self.receipt["case_id"],
                owner_kind="ANSWER_PART",
                owner_id=row.pk,
                from_backend=row.storage_backend,
                from_key=row.storage_key,
                to_backend="inline-database-v1",
                to_key=row.sha256,
                sha256=row.sha256,
                size=row.size,
                subject_id=self.common["subject_id"],
                provider_id=self.directory.provider_id,
                auth_epoch=self.directory.current.auth_epoch,
            )
        self.convert(row, InlineDatabaseStorage())
        event = CaseMediaStorageTransition.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CaseMediaStorageTransition.objects.filter(pk=event.pk).update(subject_id="other")
        with self.assertRaises(IntegrityError), transaction.atomic():
            event.delete()

    def test_storage_key_lock_encloses_database_commit(self):
        original_lock = self.storage.binding_lock
        exits = []
        depth = 0

        @contextmanager
        def checked_lock(digest):
            nonlocal depth
            depth += 1
            try:
                with original_lock(digest):
                    yield
            finally:
                depth -= 1
                if depth == 0:
                    exits.append(
                        (connection.in_atomic_block, AnswerPart.objects.filter(ordinal=2).count())
                    )

        with patch.object(self.storage, "binding_lock", side_effect=checked_lock):
            self.save()
        self.assertEqual(exits, [(False, 1)])

    def test_gc_checks_both_owner_apps_without_row_locks_and_keeps_live_pointer(self):
        row = self.attachment()
        self.assertTrue(live_references(row.storage_backend, row.storage_key))
        queries = []

        def capture(execute, sql, params, many, context):
            queries.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(capture):
            self.assertFalse(live_references("private-filesystem-v1", "0" * 64 + ".blob"))
        self.assertEqual(len(queries), 2)
        self.assertTrue(all("FOR UPDATE" not in sql for sql in queries))
        with patch(
            "apps.case_attachments.storage_bindings.apps.is_installed",
            side_effect=lambda name: name == "apps.answer_media",
        ):
            with self.assertRaisesMessage(cases.CaseConflict, "media_owner_schema_unavailable"):
                live_references(row.storage_backend, row.storage_key)
        path = self.storage.root / "objects" / row.storage_key
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        result = self.storage.collect_orphans(live_references, grace_seconds=3600, dry_run=False)
        self.assertEqual(result[0]["status"], "REFERENCED_PRESERVED")
        self.assertEqual(
            attachments.requester_read(
                token=self.receipt["token"], attachment_id=row.pk, synthetic_fixtures_only=True
            )["raw"],
            audio_fixture()["raw"],
        )

    def test_concurrent_conversion_serializes_same_owner_and_records_one_transition(self):
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=None):
            self.save()
        row = self.part()

        def convert():
            try:
                try:
                    return self.convert(row)["storage_backend"]
                except cases.CaseConflict:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: convert(), range(2)))
        self.assertCountEqual(results, ["private-filesystem-v1", "conflict"])
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 1)

    def test_gc_waits_for_new_external_reference_commit(self):
        written, allow_commit, gc_started = Event(), Event(), Event()
        original_put = self.storage.put

        def pause_after_write(media):
            result = original_put(media)
            path = self.storage.root / "objects" / result.key
            os.utime(path, (time.time() - 7200, time.time() - 7200))
            written.set()
            if not allow_commit.wait(10):
                raise RuntimeError("synthetic test timeout")
            return result

        def writer():
            try:
                return self.save()
            finally:
                connections.close_all()

        def collector():
            try:
                gc_started.set()
                return self.storage.collect_orphans(
                    live_references, grace_seconds=3600, dry_run=False
                )
            finally:
                connections.close_all()

        with patch.object(self.storage, "put", side_effect=pause_after_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                write = pool.submit(writer)
                try:
                    self.assertTrue(written.wait(10))
                    collect = pool.submit(collector)
                    self.assertTrue(gc_started.wait(10))
                    with self.assertRaises(TimeoutError):
                        collect.result(timeout=0.1)
                finally:
                    allow_commit.set()
                write.result(timeout=10)
                result = collect.result(timeout=10)
        self.assertEqual(result[0]["status"], "REFERENCED_PRESERVED")
        self.assertEqual(services.raw_for_part(self.part()), audio_fixture()["raw"])

    def test_audited_conversion_cannot_change_filename_or_other_metadata(self):
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=None):
            self.save()
        row = self.part()
        original_update = QuerySet.update

        def change_metadata(query, **fields):
            if query.model is AnswerPart:
                fields["filename"] = "changed.wav"
            return original_update(query, **fields)

        with patch.object(QuerySet, "update", new=change_metadata):
            with self.assertRaises(IntegrityError):
                self.convert(row)
        row.refresh_from_db()
        self.assertEqual(row.filename, "answer.wav")
        self.assertIsNotNone(row.original)
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 0)

    def test_schema_reverse_rejects_external_owner_until_explicit_inline_conversion(self):
        self.save()
        row = self.part()
        with self.assertRaises(DatabaseError):
            call_command("migrate", "answer_media", "0003", verbosity=0)
        self.assertEqual(services.raw_for_part(row), audio_fixture()["raw"])
        self.convert(row, InlineDatabaseStorage())
        try:
            call_command("migrate", "answer_media", "0003", verbosity=0)
        finally:
            call_command("migrate", interactive=False, verbosity=0)
        row.refresh_from_db()
        self.assertEqual(row.storage_key, row.sha256)
        self.assertEqual(services.raw_for_part(row), audio_fixture()["raw"])

    def test_forward_conversion_requires_configured_resolver_for_target_pointer(self):
        with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=None):
            self.save()
            row = self.part()
            with self.assertRaises(cases.CaseConflict):
                self.convert(row)
        row.refresh_from_db()
        self.assertEqual(row.storage_backend, "inline-database-v1")
        self.assertEqual(CaseMediaStorageTransition.objects.count(), 0)
