"""Native human classification, bootstrap management and current-session denials."""

from dataclasses import replace
from unittest.mock import patch

from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseEvidence, CaseSource
from tests.casework.test_http import WEB_SETTINGS, hidden, post

from . import management, services
from .catalog import LEVELS
from .models import ClassificationRevision
from .test_support import PrivacyFixture
from .views import STAFF_PATH

NATIVE = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.data_privacy.urls",
    "DATA_UPLOAD_MAX_NUMBER_FIELDS": 32,
    "MIDDLEWARE": [
        "apps.data_privacy.integration.PrivacyResponses",
        *WEB_SETTINGS["MIDDLEWARE"],
    ],
}


class ManagementFixture(PrivacyFixture):
    def setUp(self):
        super().setUp()
        self.originals = self.source_rows()
        self.grant_editor()

    def grant_editor(self):
        for level in ("", *LEVELS):
            self.allow(self.target, level, "VIEW_CLASSIFICATION")
        previous = ""
        for level in LEVELS:
            self.allow(self.target, level, "CLASSIFY", previous_level=previous)
            previous = level

    @staticmethod
    def source_rows():
        return [
            list(model.objects.order_by("pk").values())
            for model in (Case, CaseSource, CaseEvidence, CaseEvent, AnswerRevision)
        ]

    def login(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        page = client.get("/casework/staff/login/")
        result = post(
            client, "/casework/staff/login/", {"credential": self.directory.credential}, page
        )
        self.assertEqual(result.status_code, 303)
        return client

    def open(self, client):
        page = client.get(STAFF_PATH)
        self.assertEqual(page.status_code, 200)
        return post(
            client,
            STAFF_PATH,
            {"action": "privacy_inspect", "kind": "CASE", "identifier": self.target.identifier},
            page,
        )

    def form(self, page, level="PUBLIC"):
        fields = {
            name: hidden(page, name)
            for name in (
                "kind",
                "identifier",
                "expected_digest",
                "source_digest",
                "request_key",
                "proof",
            )
        }
        return {
            **fields,
            "action": "privacy_classify",
            "level": level,
            "note": "قرار بشري اصطناعي <script> يبقى نصًا لا شفرة",
            "confirmed": "yes",
        }


@override_settings(**NATIVE)
class ClassificationManagementTests(ManagementFixture, TransactionTestCase):
    def test_unclassified_management_is_separate_from_case_content_read(self):
        common = dict(
            provider=self.directory,
            subject_id=self.directory.current.subject_id,
            synthetic_fixtures_only=True,
        )
        catalog = management.catalog(**common)
        self.assertEqual(catalog["total"], 1)
        self.assertNotIn(self.receipt.get("token", "absent-token"), repr(catalog))
        with self.assertRaises(services.PrivacyDenied):
            cases.read_case(case_id=self.receipt["case_id"], **common)
        with management.inspect(kind="CASE", identifier=self.target.identifier, **common) as item:
            self.assertEqual(item["history"], [])
            self.assertEqual(item["digest"], services.ZERO)
        self.assertEqual(self.source_rows(), self.originals)

    def test_native_four_level_history_keeps_originals_and_does_not_grant_read(self):
        client = self.login()
        page = self.open(client)
        self.assertEqual(page.status_code, 200)
        for level in LEVELS:
            page = post(client, STAFF_PATH, self.form(page, level), page)
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, f'data-level="{level}"')
            self.assertContains(page, "&lt;script&gt;")
        self.assertEqual(
            list(ClassificationRevision.objects.order_by("number").values_list("level", flat=True)),
            list(LEVELS),
        )
        self.assertEqual(self.source_rows(), self.originals)
        with self.assertRaises(services.PrivacyDenied):
            cases.read_case(
                case_id=self.receipt["case_id"],
                provider=self.directory,
                subject_id=self.directory.current.subject_id,
                synthetic_fixtures_only=True,
            )

    def test_csrf_browser_binding_stale_form_and_scope_change_cannot_append(self):
        client, other = self.login(), self.login()
        page, other_page = self.open(client), self.open(other)
        fields = self.form(page)
        self.assertEqual(client.post(STAFF_PATH, fields).status_code, 403)
        self.assertEqual(post(other, STAFF_PATH, fields, other_page).status_code, 400)
        self.assertFalse(ClassificationRevision.objects.exists())
        saved = post(client, STAFF_PATH, fields, page)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(post(client, STAFF_PATH, fields, saved).status_code, 404)
        self.assertEqual(ClassificationRevision.objects.count(), 1)
        actor = self.directory.current
        self.directory.current = replace(actor, case_keys=frozenset({"different-case"}))
        self.assertEqual(
            post(client, STAFF_PATH, self.form(saved, "INTERNAL"), saved).status_code, 404
        )
        self.assertEqual(ClassificationRevision.objects.count(), 1)

    def test_current_policy_can_withdraw_classification_management_after_render(self):
        client = self.login()
        original = management._inspect

        def revoke_after_read(*args, **kwargs):
            value = original(*args, **kwargs)
            self.authority.grants.clear()
            return value

        with patch.object(management, "_inspect", side_effect=revoke_after_read):
            response = client.get(STAFF_PATH)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.target.identifier, status_code=404)
        self.grant_editor()
        self.assertEqual(client.get(STAFF_PATH).status_code, 200)

    def test_native_editor_denies_missing_session_query_and_unknown_targets(self):
        guest = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        self.assertEqual(guest.get(STAFF_PATH).status_code, 403)
        client = self.login()
        page = client.get(STAFF_PATH)
        self.assertIn(client.get(STAFF_PATH + "?target=all").status_code, (400, 404))
        result = post(
            client,
            STAFF_PATH,
            {
                "action": "privacy_inspect",
                "kind": "settings.AUTH_USER_MODEL",
                "identifier": self.target.identifier,
            },
            page,
        )
        self.assertEqual(result.status_code, 404)
        self.assertFalse(ClassificationRevision.objects.exists())
