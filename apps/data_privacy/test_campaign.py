"""Native shared routes keep bootstrap management separate from case reads."""

from django.test import Client, TransactionTestCase, override_settings

from apps.operational_workspace.test_support import CREDENTIALS
from tests.casework.test_http import post

from .campaign_test_support import FEATURES, CampaignFixture
from .models import ClassificationRevision
from .test_management import ManagementFixture


@override_settings(**FEATURES)
class CampaignPrivacyTests(CampaignFixture, TransactionTestCase):
    form = ManagementFixture.form

    def login(self, subject, prefix):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        response = client.get(prefix + "login/")
        self.assertEqual(response.status_code, 200)
        response = post(client, prefix + "login/", {"credential": CREDENTIALS[subject]}, response)
        self.assertEqual(response.status_code, 303)
        return client

    def test_native_staff_public_label_and_management_do_not_open_case_without_read(self):
        client = self.login("mufti", "/casework/staff/")
        page = client.get("/casework/staff/")
        self.assertContains(page, 'href="/casework/staff/privacy/"')
        self.assertNotContains(page, self.receipt["public_ref"])
        path = "/casework/staff/privacy/"
        catalog = client.get(path)
        page = post(
            client,
            path,
            {"action": "privacy_inspect", "kind": "CASE", "identifier": self.target.identifier},
            catalog,
        )
        saved = post(client, path, self.form(page), page)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(ClassificationRevision.objects.count(), 1)
        self.assertNotContains(client.get("/casework/staff/"), self.receipt["public_ref"])
        self.allow(self.target, "PUBLIC", "READ")
        self.assertContains(client.get("/casework/staff/"), self.receipt["public_ref"])
        self.assertEqual(self.source_rows(), self.originals)

    def test_native_organizer_management_keeps_current_authority_after_form_render(self):
        client = self.login("admin", "/casework/operations/")
        queue = client.get("/casework/operations/")
        self.assertContains(queue, 'href="/casework/operations/privacy/"')
        path = "/casework/operations/privacy/"
        page = post(
            client,
            path,
            {"action": "privacy_inspect", "kind": "CASE", "identifier": self.target.identifier},
            client.get(path),
        )
        self.assertEqual(page.status_code, 200)
        self.authority.grants = {
            key: grant
            for key, grant in self.authority.grants.items()
            if dict(key)["subject_id"] != "admin"
        }
        refused = post(client, path, self.form(page), page)
        self.assertEqual(refused.status_code, 404)
        self.assertNotContains(refused, self.target.identifier, status_code=404)
        self.assertEqual(ClassificationRevision.objects.count(), 0)
        self.assertEqual(self.source_rows(), self.originals)
