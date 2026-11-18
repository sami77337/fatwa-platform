"""Native CSRF forms on the integrated dispatcher with current rights/maintenance."""

from dataclasses import replace

from django.test import Client, TransactionTestCase, override_settings

from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.platform_recovery import maintenance
from tests.casework.test_http import WEB_SETTINGS, post

from .editorial_tests import EditorialFixture
from .models import EditorialBinding
from .tests import FEATURES


@override_settings(
    **{
        **WEB_SETTINGS,
        **FEATURES,
        "ROOT_URLCONF": "config.campaign_urls",
        "MIDDLEWARE": [
            "apps.platform_recovery.middleware.MaintenanceGuard",
            *WEB_SETTINGS["MIDDLEWARE"],
        ],
    }
)
class EditorialHTTPTests(EditorialFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.directory.authenticate = lambda credential: self.directory.resolve(
            {
                "synthetic-editor-credential-32-characters": "editor",
                "synthetic-independent-publisher-32-characters": "other",
            }.get(credential, "missing")
        )
        policy = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        policy.enable()
        self.addCleanup(policy.disable)
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        self.login("synthetic-editor-credential-32-characters")

    def login(self, credential):
        page = self.client.get("/casework/staff/login/")
        response = post(self.client, "/casework/staff/login/", {"credential": credential}, page)
        self.assertEqual(response.status_code, 303)
        self.page = self.client.get("/casework/staff/")

    def send(self, action, **fields):
        return post(
            self.client,
            "/casework/staff/",
            dict(action=action, publication_id=self.edition["id"], **fields),
            self.page,
        )

    def test_native_link_review_independent_approval_and_redacted_denials(self):
        page = self.send("classification_desk")
        self.assertContains(page, 'value="classification_editorial_prepare"')
        page = self.send(
            "classification_editorial_prepare",
            revision_id=self.classification["id"],
            expected_revision="4",
            expected_evidence_version="2",
            confirm="yes",
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "CANDIDATE")
        self.assertIn("no-store", page["Cache-Control"])
        binding = EditorialBinding.objects.get()
        page = self.send(
            "classification_editorial_review", binding_id=str(binding.pk), confirm="yes"
        )
        self.assertContains(page, "REVIEWED")
        page = self.send(
            "classification_editorial_approve", binding_id=str(binding.pk), confirm="yes"
        )
        self.assertEqual(page.status_code, 404)
        self.assertNotIn(b"PRIVATE", page.content)
        self.login("synthetic-independent-publisher-32-characters")
        page = self.send(
            "classification_editorial_approve", binding_id=str(binding.pk), confirm="yes"
        )
        self.assertContains(page, "PUBLISHED")
        self.assertEqual(
            PublicationAction.objects.filter(edition=binding.edition, action="APPROVE").count(), 1
        )
        page = self.send("classification_history")
        self.assertContains(page, str(binding.pk))

    def test_csrf_forged_identity_extra_fields_and_revoked_scope(self):
        binding = self.prepare()
        fields = dict(
            action="classification_editorial_inspect",
            publication_id=self.edition["id"],
            binding_id=binding["binding_id"],
        )
        self.assertEqual(self.client.post("/casework/staff/", fields).status_code, 403)
        page = self.send(
            "classification_editorial_inspect", binding_id=binding["binding_id"], subject_id="other"
        )
        self.assertEqual(page.status_code, 400)
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], case_keys=frozenset()
        )
        page = self.send("classification_editorial_inspect", binding_id=binding["binding_id"])
        self.assertEqual(page.status_code, 403)
        self.assertNotIn(b"PRIVATE", page.content)

    def test_freeze_and_disabled_drill_do_not_mutate(self):
        binding = self.prepare()
        with override_settings(FATWA_CLASSIFICATION_EDITORIAL_SIMULATION_ENABLED=False):
            page = self.send(
                "classification_editorial_review", binding_id=binding["binding_id"], confirm="yes"
            )
            self.assertEqual(page.status_code, 404)
        maintenance.enter(root=self.control, synthetic_fixtures_only=True)
        page = self.send(
            "classification_editorial_review", binding_id=binding["binding_id"], confirm="yes"
        )
        self.assertEqual(page.status_code, 503)
        self.assertEqual(PublicationEdition.objects.count(), 2)
        self.assertEqual(
            PublicationAction.objects.filter(edition_id=binding["edition_id"]).count(), 0
        )
