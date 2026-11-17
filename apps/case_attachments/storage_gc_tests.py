"""GC must preserve private bytes when any durable owner schema is unavailable."""

import os
import tempfile
import time
from unittest.mock import patch

from django.apps import apps
from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.private_media.filesystem import FileSystemStorage
from apps.private_media.validation import validate

from . import services
from .models import CaseAttachment
from .storage_bindings import live_references, reference


@override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True)
class StorageOwnerSchemaTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fatwa-v9-gc-owner-")
        self.addCleanup(temporary.cleanup)
        self.storage = FileSystemStorage(temporary.name, synthetic_fixtures_only=True)
        configured = override_settings(FATWA_PRIVATE_MEDIA_STORAGE=self.storage)
        configured.enable()
        self.addCleanup(configured.disable)
        receipt = cases.intake_case(
            original_question="synthetic GC owner question",
            requester_id="gc-requester",
            source_event_id="gc-event",
            idempotency_key="gc-intake",
            synthetic_fixtures_only=True,
        )
        uploaded = services.upload(
            token=receipt["token"],
            raw=b"synthetic private original\n",
            filename="fixture.txt",
            media_type="text/plain",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        self.row = CaseAttachment.objects.get(pk=uploaded["id"])
        self.original = reference(self.row)
        self.path = self.storage.root / "objects" / self.row.storage_key
        old = time.time() - 7200
        os.utime(self.path, (old, old))

    def test_missing_either_owner_app_preserves_old_referenced_blob_without_queries(self):
        installed = apps.is_installed
        for missing in ("apps.case_attachments", "apps.answer_media"):
            with (
                self.subTest(missing=missing),
                patch(
                    "apps.case_attachments.storage_bindings.apps.is_installed",
                    side_effect=lambda name: name != missing and installed(name),
                ),
                self.assertNumQueries(0),
            ):
                with self.assertRaisesMessage(cases.CaseConflict, "media_owner_schema_unavailable"):
                    live_references(self.original)
                result = self.storage.collect_orphans(
                    live_references, grace_seconds=3600, dry_run=False
                )
                self.assertEqual(result[0]["status"], "REFERENCE_UNAVAILABLE_PRESERVED")
                self.assertTrue(self.path.exists())
                self.assertEqual(self.storage.get(self.original), b"synthetic private original\n")

    def test_missing_model_registry_preserves_blob_without_partial_reference_queries(self):
        model = apps.get_model

        def unavailable(label, name):
            if label == "answer_media":
                raise LookupError("unavailable owner")
            return model(label, name)

        with patch(
            "apps.case_attachments.storage_bindings.apps.get_model", side_effect=unavailable
        ):
            with self.assertNumQueries(0):
                result = self.storage.collect_orphans(
                    live_references, grace_seconds=3600, dry_run=False
                )
            self.assertEqual(result[0]["status"], "REFERENCE_UNAVAILABLE_PRESERVED")
        self.assertTrue(self.path.exists())

    def test_complete_owner_registry_preserves_reference_and_collects_true_orphan(self):
        media = validate(b"synthetic unreferenced bytes\n", "orphan.txt", "text/plain")
        orphan = self.storage.put(media)
        orphan_path = self.storage.root / "objects" / orphan.key
        old = time.time() - 7200
        os.utime(orphan_path, (old, old))
        result = self.storage.collect_orphans(live_references, grace_seconds=3600, dry_run=False)
        states = {item["key"]: item["status"] for item in result}
        self.assertEqual(states[self.original.key], "REFERENCED_PRESERVED")
        self.assertEqual(states[orphan.key], "REMOVED")
        self.assertFalse(orphan_path.exists())
        self.assertEqual(self.storage.get(self.original), b"synthetic private original\n")
