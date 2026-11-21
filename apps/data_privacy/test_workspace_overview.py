"""The connected frame cannot reconstruct children filtered by case READ."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.mufti_workspace import context
from apps.private_media.test_signed_links import FEATURES, PrivateOriginalFixture
from apps.team_workspace import presentation, views
from tests.casework.test_http import post

from . import services, test_private_hooks
from .catalog import locate
from .test_support import Authority, PrivacyFixture


@override_settings(
    **{k: v for k, v in FEATURES.items() if k != "MIDDLEWARE"},
    FATWA_MUFTI_WORKSPACE_ENABLED=True,
)
class WorkspaceOverviewPrivacyTests(PrivateOriginalFixture, TransactionTestCase):
    principal = PrivacyFixture.principal
    allow = PrivacyFixture.allow
    classify = PrivacyFixture.classify
    admit = test_private_hooks.PrivateClassificationTests.admit
    admit_answer = test_private_hooks.PrivateClassificationTests.admit_answer

    def setUp(self):
        super().setUp()
        self.before = self.originals()
        self.authority = Authority()
        self.target = locate("CASE", self.receipt["case_id"])
        self.enterContext(
            override_settings(
                FATWA_DATA_PRIVACY_ENABLED=True,
                FATWA_DATA_PRIVACY_AUTHORITY=self.authority,
            )
        )
        self.admit("CASE", self.target.identifier)

    def overview(self):
        return post(
            self.staff,
            "/casework/staff/",
            {"action": "case_workspace", "case_ref": self.receipt["public_ref"]},
            self.staff.get("/casework/staff/"),
        )

    def test_native_overview_does_not_reconstruct_hidden_answer_or_attachment_history(self):
        snapshot = presentation.read_workspace_case(**self.common)
        self.assertEqual(snapshot["answers"], [])
        self.assertIsNone(snapshot["answer_manifest"])
        self.assertEqual([row["sequence"] for row in snapshot["timeline"]], [1])
        page = self.overview()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertNotContains(page, "PRIVATE synthetic original answer")
        self.assertNotContains(page, "private-question.wav")
        self.assertNotContains(page, str(self.part.pk))
        self.assertEqual(self.originals(), self.before)
        self.admit_answer()
        self.admit("ATTACHMENT", self.attachment["id"])
        page = self.overview()
        self.assertContains(page, "PRIVATE synthetic original answer")
        self.assertContains(page, "private-question.wav")
        self.assertEqual(self.originals(), self.before)

    def test_manifest_and_count_require_exact_child_read_before_core_or_frame_projection(self):
        self.admit("ANSWER", self.part.manifest.answer_id)
        snapshot = presentation.read_workspace_case(**self.common, include_answer_manifest=False)
        attachments, manifest, release, _ = context._metadata(self.common, snapshot)
        self.assertEqual(attachments, [])
        self.assertIsNone(manifest)
        self.assertFalse(release["recorded"])
        with self.assertRaises(services.PrivacyDenied):
            presentation.read_workspace_case(**self.common)
        for identifier in AnswerPart.objects.filter(manifest=self.part.manifest).values_list(
            "pk", flat=True
        ):
            self.admit("ANSWER_PART", identifier)
        value = presentation.read_workspace_case(**self.common)
        self.assertEqual(value["answer_manifest"]["answer_id"], str(self.part.manifest.answer_id))
        self.assertEqual(len(value["answer_manifest"]["parts"]), 2)
        self.assertEqual(self.originals(), self.before)

    def test_child_revocation_after_native_render_discards_all_earlier_frame_data(self):
        self.admit_answer()
        key = self.admit("ATTACHMENT", self.attachment["id"])
        render = views.render

        def render_then_revoke(*args, **kwargs):
            response = render(*args, **kwargs)
            self.authority.grants.pop(key, None)
            return response

        previous = self.staff.get("/casework/staff/")
        with patch.object(views, "render", side_effect=render_then_revoke):
            page = post(
                self.staff,
                "/casework/staff/",
                {"action": "case_workspace", "case_ref": self.receipt["public_ref"]},
                previous,
            )
        self.assertEqual(page.status_code, 404)
        self.assertNotContains(page, "private-question.wav", status_code=404)
        self.assertNotContains(page, self.receipt["public_ref"], status_code=404)
        self.admit("ATTACHMENT", self.attachment["id"])
        self.assertContains(self.overview(), "private-question.wav")
        self.assertEqual(cases.read_case(**self.common)["public_ref"], self.receipt["public_ref"])
        self.assertEqual(self.originals(), self.before)
