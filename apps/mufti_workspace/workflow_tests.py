"""Current-case next actions use canonical versions and recorded independent releases."""

from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from tests.casework.test_http import post

from . import tests as fixtures


@override_settings(FATWA_MUFTI_WORKSPACE_ENABLED=True, FATWA_CASEWORK_WEB_ENABLED=True)
class WorkflowTests(TransactionTestCase):
    setUp = fixtures.MuftiWorkspaceTests.setUp
    open = fixtures.MuftiWorkspaceTests.open
    mutation = fixtures.MuftiWorkspaceTests.mutation
    request = fixtures.MuftiWorkspaceTests.request

    def work(self, page):
        return page.context["mufti_workspace"]["workflow"]

    def test_received_draft_review_approval_change_next_actions_without_extra_writes(self):
        page = self.open()
        self.assertContains(page, 'id="mufti-next-actions"')
        self.assertEqual(self.work(page)["primary"]["fragment"], "editor")
        self.assertEqual([row["code"] for row in self.work(page)["blockers"]], ["ANSWER_REQUIRED"])
        self.assertEqual(CaseEvent.objects.count(), 1)
        page = self.mutation(page, "draft", text="صياغة بشرية للمراجعة")
        self.assertEqual(self.work(page)["primary"]["fragment"], "review")
        self.assertEqual(self.work(page)["blockers"], [])
        current = page.context["mufti_workspace"]["case"]
        page = self.mutation(page, "approve", answer_id=current["latest_answer"]["id"], note="")
        steps = {row["key"]: row for row in self.work(page)["steps"]}
        self.assertEqual(steps["review"]["state"], "RECORDED")
        self.assertEqual(steps["private"]["state"], "NOT_APPLICABLE")
        self.assertIsNone(self.work(page)["delivery_verified"])
        self.assertIsNone(self.work(page)["read_confirmed"])
        self.assertEqual(CaseEvent.objects.count(), 3)

    def test_pending_clarification_does_not_offer_an_edit_or_approval_shortcut(self):
        page = self.open()
        page = self.mutation(page, "clarify", text="كيف حدث المثال الاصطناعي؟")
        work = self.work(page)
        self.assertEqual(work["primary"]["fragment"], "mufti-facts-heading")
        self.assertIn("CLARIFICATION_PENDING", [row["code"] for row in work["blockers"]])
        self.assertNotContains(page, 'id="answer-text"')
        self.assertNotContains(page, 'value="approve"')
        self.assertEqual(Case.objects.get().stage, "NEEDS_CLARIFICATION")

    def test_only_evidence_newer_than_answer_basis_is_in_changes_panel(self):
        cases.add_followup(
            token=self.receipt["token"],
            text="تفصيل سابق دخل في أساس الجواب",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        page = self.open()
        page = self.mutation(page, "draft", text="جواب على الوقائع الثانية")
        cases.add_followup(
            token=self.receipt["token"],
            text="واقعة جديدة بعد الجواب",
            expected_revision=3,
            synthetic_fixtures_only=True,
        )
        page = self.open(page)
        work = self.work(page)
        self.assertEqual(work["answer_evidence_version"], 2)
        self.assertEqual(
            work["changed_evidence"], [{"version": 3, "text": "واقعة جديدة بعد الجواب"}]
        )
        self.assertEqual(work["primary"]["fragment"], "mufti-evidence-changes")
        self.assertIn("EVIDENCE_CHANGED", [row["code"] for row in work["blockers"]])
        self.assertContains(page, 'id="mufti-evidence-changes"')
        self.assertNotContains(page, 'value="approve"')
        self.assertEqual(Case.objects.get().answers.count(), 1)

    def test_return_reason_is_exact_escaped_and_action_uses_current_case(self):
        page = self.mutation(self.open(), "draft", text="مسودة بشرية")
        current = page.context["mufti_workspace"]["case"]
        reason = "<script>not executable</script> وضح مناط المثال"
        page = self.mutation(page, "return", answer_id=current["latest_answer"]["id"], note=reason)
        work = self.work(page)
        self.assertEqual(work["return_reason"], reason)
        self.assertEqual(work["primary"]["action"], "case_workspace")
        self.assertEqual(work["primary"]["fragment"], "editor")
        self.assertNotContains(page, "<script>")
        self.assertContains(page, 'id="mufti-return-reason"')
        before = CaseEvent.objects.count()
        self.client.cookies["fatwa_team_panel"] = "delivery"
        response = post(
            self.client,
            "/casework/staff/",
            {"action": work["primary"]["action"], "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["mufti_workspace"]["case"]["public_ref"], self.receipt["public_ref"]
        )
        self.assertEqual(CaseEvent.objects.count(), before)

    @override_settings(FATWA_ANSWER_MEDIA_ENABLED=True, FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True)
    def test_current_release_is_recorded_without_promising_current_access_or_delivery(self):
        from apps.answer_media import services as media
        from apps.answer_media.models import AnswerManifest, PrivateAnswerRelease

        media.save_multipart_answer(
            **self.common,
            text="جواب بشري مع جزء",
            files=[{"raw": b"synthetic", "filename": "part.txt", "media_type": "text/plain"}],
            expected_revision=1,
            expected_evidence_version=1,
        )
        page = self.open()
        current = page.context["mufti_workspace"]["case"]
        page = self.mutation(page, "approve", answer_id=current["latest_answer"]["id"], note="")
        work = self.work(page)
        self.assertEqual(work["primary"]["action"], "answer_media")
        self.assertEqual(work["steps"][-1]["state"], "NEEDS_EXPLICIT_RELEASE")
        current = page.context["mufti_workspace"]["case"]
        manifest = AnswerManifest.objects.get(answer_id=current["approved_answer_id"])
        media.release_private(
            **self.common,
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            manifest_sha256=manifest.sha256,
            confirmed=True,
        )
        page = self.open(page)
        work = self.work(page)
        self.assertTrue(work["release_recorded"])
        self.assertEqual(work["steps"][-1]["state"], "RECORDED_NOT_VERIFIED")
        self.assertFalse(page.context["mufti_workspace"]["verification_checked"])
        self.assertIsNone(work["delivery_verified"])
        with override_settings(FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=False):
            page = self.open(page)
            self.assertEqual(self.work(page)["steps"][-1]["state"], "DISABLED")
        current = cases.read_case(**self.common)
        media.save_multipart_answer(
            **self.common,
            text="نسخة جديدة تحتاج مراجعة",
            files=[
                {"raw": b"replacement synthetic", "filename": "new.txt", "media_type": "text/plain"}
            ],
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        page = self.open(page)
        self.assertFalse(self.work(page)["release_recorded"])
        self.assertEqual(self.work(page)["steps"][-1]["state"], "WAITING_APPROVAL")
        self.assertEqual(PrivateAnswerRelease.objects.count(), 1)

    @override_settings(
        FATWA_CASE_CITATIONS_ENABLED=False,
        FATWA_CASE_ATTACHMENTS_ENABLED=False,
        FATWA_ANSWER_MEDIA_ENABLED=False,
        FATWA_COMPOSITE_DELIVERY_ENABLED=False,
    )
    def test_closed_optional_panels_are_not_recommended_and_context_stays_metadata_only(self):
        from .context import case_workspace

        with (
            patch(
                "apps.private_media.storage.read_original",
                side_effect=AssertionError("no file I/O"),
            ),
            patch(
                "apps.private_media.validation.validate", side_effect=AssertionError("no parser")
            ),
        ):
            result = case_workspace(self.request())["mufti_workspace"]
        self.assertEqual(result["workflow"]["actions"], [])
        self.assertEqual(result["workflow"]["primary"]["action"], "case_workspace")
        self.assertNotIn("rights_verified", result["workflow"])
        self.assertEqual(CaseEvent.objects.count(), 1)
