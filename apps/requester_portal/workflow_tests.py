"""V11 one-step requester replies, safe retry and canonical Mufti handoff."""

import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TransactionTestCase, override_settings

from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvidence
from apps.casework_web import requester_workspace
from apps.private_media.filesystem import FileSystemStorage
from apps.team_workspace.presentation import read_workspace_case
from tests.casework.test_http import hidden, post

from . import notices, services
from .test_support import PORTAL_SETTINGS, PortalFixture

URL = "/casework/status/"
FILE = dict(raw=b"synthetic clarification file", filename="reply.txt", media_type="text/plain")


@override_settings(**PORTAL_SETTINGS)
class ReplyServiceTests(PortalFixture, TransactionTestCase):
    def clarify(self):
        cases.request_clarification(
            **self.staff(),
            text="وضح المسألة بملف",
            expected_revision=1,
            expected_evidence_version=1,
        )

    def submit(self, **changes):
        args = dict(
            token=self.a["token"],
            text="  رد حرفي\nمع سطر ثان  ",
            expected_revision=2,
            attachment=FILE,
            synthetic_fixtures_only=True,
        )
        return services.submit_reply(**{**args, **changes})

    def test_one_step_reply_file_under_external_lock_reaches_existing_mufti_workspace(self):
        self.clarify()
        with tempfile.TemporaryDirectory(prefix="v11-reply-") as root:
            storage = FileSystemStorage(root, synthetic_fixtures_only=True)
            with override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage):
                saved = self.submit()
                self.assertEqual((saved["revision"], saved["evidence_version"]), (4, 3))
                self.assertEqual(saved["status"], "UNDER_REVIEW")
                row = CaseAttachment.objects.get()
                self.assertEqual(row.storage_backend, "private-filesystem-v1")
                self.assertIsNone(row.original)
                self.assertEqual(
                    attachments.staff_read(**self.staff(), attachment_id=str(row.pk))["raw"],
                    FILE["raw"],
                )
                staff = read_workspace_case(**self.staff())
                self.assertEqual(staff["case_id"], self.a["case_id"])
                self.assertEqual(staff["followups"][0]["text"], "  رد حرفي\nمع سطر ثان  ")
                result = services.snapshot(token=self.a["token"], synthetic_fixtures_only=True)
                journey = services.journey(result)
                self.assertEqual(
                    [r["kind"] for r in journey["timeline"]],
                    ["question", "clarification", "followup", "attachment"],
                )
                self.assertEqual(journey["timeline"][-1]["attachment_id"], str(row.pk))
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(CaseEvidence.objects.count(), 3)

    def test_storage_failure_rolls_back_reply_evidence_and_pending_clarification(self):
        self.clarify()
        with tempfile.TemporaryDirectory(prefix="v11-failed-reply-") as root:
            storage = FileSystemStorage(root, synthetic_fixtures_only=True)
            with (
                override_settings(FATWA_PRIVATE_MEDIA_STORAGE=storage),
                patch.object(storage, "put", side_effect=OSError("disk failed")) as failed_put,
            ):
                with self.assertRaises(cases.CaseConflict):
                    self.submit()
                failed_put.assert_called_once()
        status = cases.requester_status(self.a["token"], synthetic_fixtures_only=True)
        self.assertEqual(status["status"], "NEEDS_CLARIFICATION")
        self.assertEqual((status["revision"], status["evidence_version"]), (2, 1))
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.assertEqual(CaseAttachment.objects.count(), 0)

    def test_stale_repeat_invalid_file_and_disabled_media_do_not_save_partial_text(self):
        self.clarify()
        with self.assertRaises(cases.CaseConflict):
            self.submit(attachment={**FILE, "raw": b"\x00"})
        with override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                self.submit()
        self.assertEqual(CaseEvidence.objects.count(), 1)
        self.submit()
        for _ in range(2):
            with self.assertRaises(cases.CaseConflict):
                self.submit()
        self.assertEqual(CaseEvidence.objects.count(), 3)
        self.assertEqual(CaseAttachment.objects.count(), 1)

    def test_reply_file_closes_released_answer_and_only_current_case_changes(self):
        self.approve()
        self.release()
        other = self.intake("other")
        current = cases.read_case(**self.staff())
        self.submit(expected_revision=current["revision"])
        result = services.snapshot(token=self.a["token"], synthetic_fixtures_only=True)
        self.assertIsNone(result["answer"])
        self.assertIsNone(Case.objects.get(pk=self.a["case_id"]).approved_answer_id)
        self.assertEqual(
            cases.requester_status(other["token"], synthetic_fixtures_only=True)["revision"], 1
        )


@override_settings(**PORTAL_SETTINGS)
class ReplyFormTests(PortalFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = self.client_for()

    def reply(
        self, page=None, *, with_file=True, consent=True, text="نص الرد الاصطناعي", **changes
    ):
        page = page or self.client.get(URL)
        fields = dict(
            action="reply",
            text=text,
            revision=hidden(page, "revision"),
            form_proof=hidden(page, "form_proof"),
            csrfmiddlewaretoken=hidden(page, "csrfmiddlewaretoken"),
        )
        if with_file:
            fields.update(
                synthetic_only="yes",
                reply_attachment=SimpleUploadedFile(
                    FILE["filename"], FILE["raw"], content_type=FILE["media_type"]
                ),
            )
        if not consent:
            fields.pop("synthetic_only", None)
        fields.update(changes)
        return self.client.post(URL, fields)

    def test_combined_reply_native_form_notice_once_refresh_does_not_resubmit(self):
        cases.request_clarification(
            **self.staff(), text="استيضاح", expected_revision=1, expected_evidence_version=1
        )
        page = self.client.get(URL)
        self.assertContains(page, "مطلوب توضيح منك")
        self.assertContains(page, 'name="reply_attachment"')
        response = self.reply(page)
        self.assertEqual(response.status_code, 303, response.content)
        cookie = response.cookies[notices.COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertNotIn("نص الرد الاصطناعي", cookie.value)
        page = self.client.get(URL)
        self.assertContains(page, "حُفظ ردك ومرفقه معًا")
        self.assertContains(page, 'data-history-kind="attachment"')
        again = self.client.get(URL)
        self.assertNotContains(again, "حُفظ ردك ومرفقه معًا")
        self.assertEqual(CaseEvidence.objects.count(), 3)
        self.assertEqual(CaseAttachment.objects.count(), 1)
        self.assertEqual(self.reply(page, with_file=False).status_code, 303)
        self.assertContains(self.client.get(URL), "حُفظ ردك ضمن القضية")

    def test_native_empty_optional_file_is_text_reply_but_dual_file_fields_rejected(self):
        response = self.reply(with_file=False, reply_attachment="")
        self.assertEqual(response.status_code, 303, response.content)
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual(CaseEvidence.objects.count(), 2)
        self.assertContains(self.client.get(URL), "حُفظ ردك ضمن القضية")
        rejected = self.reply(with_file=False, reply_attachment="forged-file-text")
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(CaseEvidence.objects.count(), 2)

    def test_stale_error_retains_text_and_new_pins_file_must_be_selected_again(self):
        page = self.client.get(URL)
        cases.add_followup(
            token=self.a["token"],
            text="وقائع أحدث",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        failed = self.reply(page, text="مسودة يجب حفظها للنسخ")
        self.assertContains(failed, "مسودة يجب حفظها للنسخ", status_code=409)
        self.assertContains(failed, "اختر الملف مجددًا", status_code=409)
        self.assertEqual(hidden(failed, "revision"), "2")
        self.assertEqual(CaseAttachment.objects.count(), 0)
        self.assertEqual(CaseEvidence.objects.count(), 2)

    def test_missing_file_consent_oversize_extra_fields_csrf_do_not_write(self):
        page = self.client.get(URL)
        missing = self.reply(page, consent=False)
        self.assertContains(missing, "نص الرد الاصطناعي", status_code=400)
        self.assertEqual(self.reply(page, form_proof="ع" * 64).status_code, 409)
        oversized = self.reply(
            page,
            reply_attachment=SimpleUploadedFile(
                "large.txt", b"x" * 192001, content_type="text/plain"
            ),
        )
        self.assertContains(oversized, "نص الرد الاصطناعي", status_code=413)
        self.assertEqual(self.reply(page, case_id=self.a["case_id"]).status_code, 400)
        self.assertEqual(self.reply(page, csrfmiddlewaretoken="bad").status_code, 403)
        self.assertEqual(CaseEvidence.objects.count(), 1)

    def test_cross_case_form_and_notice_replay_do_not_transfer_text_or_receipt(self):
        old = self.client.get(URL)
        self.assertEqual(self.reply(old).status_code, 303)
        notice = self.client.cookies[notices.COOKIE].value
        other = self.intake("other")
        page = self.client.get(URL)
        post(self.client, URL, dict(action="unlock", token=other["token"]), page)
        self.client.cookies[notices.COOKIE] = notice
        page = self.client.get(URL)
        self.assertNotContains(page, "حُفظ ردك ومرفقه معًا")
        failed = self.reply(old, text="PRIVATE_OLD_CASE_TEXT")
        self.assertNotContains(failed, "PRIVATE_OLD_CASE_TEXT", status_code=409)
        self.assertEqual(Case.objects.get(pk=other["case_id"]).revision, 1)
        self.client.cookies[notices.COOKIE] = notice + "corrupted"
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_transient_snapshot_failure_keeps_session_and_never_shows_cached_private_data(self):
        cookie = self.client.cookies[requester_workspace.COOKIE].value
        for failure in (
            cases.CaseConflict("private_original_integrity_failed"),
            DatabaseError("unavailable"),
        ):
            with patch.object(services, "snapshot", side_effect=failure):
                response = self.client.get(URL)
            self.assertContains(response, "إعادة تحميل قضيتي", status_code=503)
            self.assertNotContains(response, 'id="portal-token"', status_code=503)
            self.assertNotContains(response, "سؤال اصطناعي حرفي", status_code=503)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertEqual(self.client.cookies[requester_workspace.COOKIE].value, cookie)
        self.assertContains(self.client.get(URL), "سؤال اصطناعي حرفي")
        cases.revoke_access(**self.staff(), requester_id="requester-a")
        response = self.client.get(URL)
        self.assertContains(response, 'id="portal-token"')
        self.assertNotContains(response, "سؤال اصطناعي حرفي")
