"""Native shared dispatcher/navigation and strict admission for classification."""

import tempfile
from pathlib import Path

from django.test import Client, TransactionTestCase, override_settings

from apps.classification_review import services
from apps.classification_review.models import ClassificationAction, ClassificationRevision
from apps.classification_review.tests import FEATURES, Fixture
from apps.platform_recovery import maintenance
from apps.platform_recovery.integration import MaintenanceUnavailable
from apps.private_media.filesystem import FileSystemStorage
from apps.source_rights import services as rights
from apps.source_rights.tests import Authority as RightsAuthority
from tests.casework.test_http import WEB_SETTINGS, post


@override_settings(**{**FEATURES, **WEB_SETTINGS, "ROOT_URLCONF": "config.campaign_urls"})
class ClassificationWiringTests(Fixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="v13-classification-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        storage = FileSystemStorage(root / "private", synthetic_fixtures_only=True)
        self.control = root / "control"
        self.control.mkdir(mode=0o700)
        maintenance.initialize(root=self.control, storage=storage, synthetic_fixtures_only=True)
        policy = override_settings(
            FATWA_SOURCE_RIGHTS_ENABLED=True,
            FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(self.receipt["public_ref"]),
            FATWA_RECOVERY_MAINTENANCE_REQUIRED=True,
            FATWA_RECOVERY_MAINTENANCE_ROOT=str(self.control),
            FATWA_PRIVATE_MEDIA_STORAGE=storage,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_MUFTI_WORKSPACE_ENABLED=True,
            MIDDLEWARE=["apps.platform_recovery.middleware.MaintenanceGuard", *WEB_SETTINGS["MIDDLEWARE"]],
        )
        policy.enable()
        self.addCleanup(policy.disable)
        source = rights.register(**self.common, kind="TOC_METADATA", target_id=self.heading.pk)
        grant = rights.propose(
            **self.common, source_id=source["id"], expected_number=0,
            uses=["READ", "CITE", "RELATE", "PREVIEW_METADATA"],
            basis="synthetic reviewed permission", note="synthetic", ttl_minutes=30,
        )
        rights.review(
            **{**self.common, "subject_id": "publisher"}, revision_id=grant["id"],
            action="APPROVE", confirmed=True, note="synthetic independent review",
        )
        strict = override_settings(FATWA_SOURCE_RIGHTS_ENFORCED=True)
        strict.enable()
        self.addCleanup(strict.disable)
        self.client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = self.client.get("/casework/staff/login/")
        post(self.client, "/casework/staff/login/", {"credential": "synthetic-editor-credential-32-characters"}, page)
        self.page = self.client.get("/casework/staff/")

    def open(self, action="classification_desk", **fields):
        return post(self.client, "/casework/staff/", {
            "action": action, "publication_id": self.edition["id"], **fields,
        }, self.page)

    def test_native_navigation_scope_and_independent_pending_state(self):
        publication = post(self.client, "/casework/staff/", {
            "action": "pub_read", "edition_id": self.edition["id"],
        }, self.page)
        self.assertContains(publication, 'value="classification_desk"')
        page = self.open()
        self.assertContains(page, self.receipt["public_ref"])
        self.assertContains(page, 'value="classification_propose"')
        page = self.open("classification_propose", knowledge_id=self.source["id"],
                         label="تصنيف تجريبي", reason="فهرس فقط", replaces_id="")
        self.assertContains(page, "PROPOSED")
        self.assertNotContains(page, 'value="classification_approve"')
        self.assertEqual(ClassificationAction.objects.count(), 0)
        self.assertEqual(ClassificationRevision.objects.count(), 1)
        row = ClassificationRevision.objects.get()
        forged = self.open("classification_approve", revision_id=str(row.pk), note="self", confirm="yes")
        self.assertEqual(forged.status_code, 404)
        self.assertEqual(ClassificationAction.objects.count(), 0)

    def test_freeze_blocks_shared_http_and_service_without_insert(self):
        self.assertEqual(maintenance.enter(root=self.control, synthetic_fixtures_only=True)["phase"], "FROZEN")
        response = self.open("classification_propose", knowledge_id=self.source["id"],
                             label="blocked", reason="blocked", replaces_id="")
        self.assertEqual(response.status_code, 503)
        with self.assertRaises(MaintenanceUnavailable):
            self.proposal()
        self.assertEqual(ClassificationRevision.objects.count(), 0)

    def test_opt_out_and_cross_scope_navigation_fail_closed(self):
        with override_settings(FATWA_CLASSIFICATION_REVIEW_ENABLED=False):
            self.assertEqual(self.open().status_code, 404)
        with override_settings(FATWA_CLASSIFICATION_REVIEW_AUTHORITY=None):
            self.assertEqual(self.open().status_code, 404)
        self.assertEqual(self.open(case_ref=self.receipt["public_ref"]).status_code, 400)
        self.assertEqual(ClassificationRevision.objects.count(), 0)
        self.assertTrue(services.desk(**self.access)["public_ref"])
