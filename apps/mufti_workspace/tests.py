"""Connected native forms and last-moment current-scope checks on synthetic PostgreSQL."""

import secrets
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import urlencode

from django.test import Client, RequestFactory, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.mufti_review.identity import IdentityUnavailable
from tests.casework.test_http import Directory, hidden, post

from . import context


def new_case(question="سؤال اصطناعي أصلي كما وصل"):
    key = secrets.token_hex(12)
    return cases.intake_case(
        original_question=question,
        source_event_id=key,
        requester_id="requester-" + key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )


@override_settings(FATWA_MUFTI_WORKSPACE_ENABLED=True, FATWA_CASEWORK_WEB_ENABLED=True)
class MuftiWorkspaceTests(TransactionTestCase):
    def setUp(self):
        self.receipt = new_case()
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = {
            "case_id": self.receipt["case_id"],
            "subject_id": self.directory.current.subject_id,
            "provider": self.directory,
            "synthetic_fixtures_only": True,
        }
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        page = self.client.get("/casework/staff/login/")
        response = post(
            self.client, "/casework/staff/login/", {"credential": self.directory.credential}, page
        )
        self.assertEqual(response.status_code, 303)
        self.queue = self.client.get("/casework/staff/")

    def open(self, page=None, **fields):
        return post(
            self.client,
            "/casework/staff/",
            {"action": "case_workspace", "case_ref": self.receipt["public_ref"], **fields},
            page or self.queue,
        )

    def mutation(self, page, action, **extra):
        current = page.context["mufti_workspace"]["case"]
        return post(
            self.client,
            "/casework/staff/",
            {
                "action": action,
                "case_ref": current["public_ref"],
                "revision": str(current["revision"]),
                "evidence_version": str(current["evidence_version"]),
                **extra,
            },
            page,
        )

    def request(self, *, path="/casework/staff/", method="POST", fields=None):
        factory = RequestFactory()
        request = (
            factory.post(
                path, fields or {"action": "case_workspace", "case_ref": self.receipt["public_ref"]}
            )
            if method == "POST"
            else factory.get(path)
        )
        request.COOKIES = {key: value.value for key, value in self.client.cookies.items()}
        request.META["CSRF_COOKIE"] = self.client.cookies["fatwa_casework_csrf"].value
        return request

    def test_new_screen_edits_returns_revises_and_approves_existing_canonical_case(self):
        self.assertNotContains(self.queue, 'id="mufti-case-reference"')
        page = self.open()
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, 'id="mufti-case-reference"')
        self.assertContains(page, self.receipt["public_ref"])
        self.assertContains(page, "سؤال اصطناعي أصلي كما وصل")
        self.assertEqual(CaseEvent.objects.count(), 1)
        page = self.mutation(page, "draft", text="صياغة بشرية أولى")
        current = page.context["mufti_workspace"]["case"]
        self.assertEqual((current["revision"], current["latest_answer"]["revision"]), (2, 1))
        page = self.mutation(
            page, "return", answer_id=current["latest_answer"]["id"], note="توضيح يحتاج تعديلًا"
        )
        self.assertContains(page, "توضيح يحتاج تعديلًا")
        self.assertNotContains(page, 'value="approve"')
        page = self.mutation(page, "draft", text="صياغة بشرية منقحة")
        answer = page.context["mufti_workspace"]["case"]["latest_answer"]
        page = self.mutation(page, "approve", answer_id=answer["id"], note="اعتماد بشري اصطناعي")
        self.assertTrue(page.context["mufti_workspace"]["approved"])
        self.assertContains(page, "الاعتماد المسجل مطابق للوقائع الحالية")
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(Case.objects.get().answers.count(), 2)
        self.assertEqual(Case.objects.get().decisions.count(), 2)

    def test_clarification_reply_stale_draft_and_new_facts_use_current_versions(self):
        page = self.open()
        page = self.mutation(page, "draft", text="مسودة قديمة")
        stale = page
        page = self.mutation(page, "clarify", text="يرجى توضيح الوقائع")
        self.assertNotContains(page, 'id="answer-text"')
        self.assertNotContains(page, 'value="approve"')
        current = cases.requester_status(self.receipt["token"], synthetic_fixtures_only=True)
        cases.add_followup(
            token=self.receipt["token"],
            text="تعقيب جديد من السائل",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        attempted = "<script>synthetic</script> محاولة غير محفوظة"
        rejected = self.mutation(stale, "draft", text=attempted)
        self.assertEqual(rejected.status_code, 409, rejected.content)
        self.assertContains(rejected, "تعقيب جديد من السائل", status_code=409)
        self.assertContains(rejected, 'id="stale-answer"', status_code=409)
        self.assertNotContains(rejected, "<script>", status_code=409)
        self.assertNotContains(rejected, 'value="approve"', status_code=409)
        self.assertEqual(rejected.context["mufti_workspace"]["case"]["evidence_version"], 2)
        self.assertEqual(Case.objects.get().answers.count(), 1)

    def test_off_nonstaff_get_and_unselected_requests_do_not_expose_context(self):
        with override_settings(FATWA_MUFTI_WORKSPACE_ENABLED=False):
            self.assertEqual(context.case_workspace(self.request()), {})
            page = post(
                self.client,
                "/casework/staff/",
                {"action": "open", "case_ref": self.receipt["public_ref"]},
                self.queue,
            )
            self.assertNotContains(page, 'id="mufti-case-reference"')
        for request in (
            self.request(method="GET"),
            self.request(path="/casework/status/"),
            self.request(fields={"action": "pub_library", "query": ""}),
        ):
            request.COOKIES["fatwa_team_panel"] = self.receipt["public_ref"]
            self.assertEqual(context.case_workspace(request), {})

    def test_foreign_case_duplicate_selection_and_non_mufti_fail_closed(self):
        foreign = new_case("FOREIGN CONTENT MUST NOT LEAK")
        denied = self.open(case_ref=foreign["public_ref"])
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn(b"FOREIGN CONTENT", denied.content)
        request = self.request()
        fields = request.POST.copy()
        fields.setlist("case_ref", [self.receipt["public_ref"], foreign["public_ref"]])
        request.POST = fields
        with self.assertRaises(cases.CaseConflict):
            context.case_workspace(request)
        self.directory.current = replace(self.directory.current, role="ORGANIZER_ADMIN")
        with self.assertRaises(IdentityUnavailable):
            context.case_workspace(self.request())

    def test_revocation_during_projection_propagates_and_suppresses_prior_private_body(self):
        original = context._metadata

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            self.directory.current = replace(self.directory.current, active=False)
            return result

        with patch("apps.mufti_workspace.context._metadata", side_effect=revoke):
            response = self.open()
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotIn("سؤال اصطناعي أصلي".encode(), response.content)
        self.assertEqual(CaseEvent.objects.count(), 1)

    def test_concurrent_facts_change_between_snapshot_and_metadata_does_not_mix_versions(self):
        original = context.presentation.read_workspace_case

        def change_after_snapshot(**kwargs):
            result = original(**kwargs)
            if kwargs.get("include_answer_manifest") is False:
                cases.add_followup(
                    token=self.receipt["token"],
                    text="وقائع متزامنة",
                    expected_revision=result["revision"],
                    synthetic_fixtures_only=True,
                )
            return result

        with patch(
            "apps.mufti_workspace.context.presentation.read_workspace_case",
            side_effect=change_after_snapshot,
        ):
            response = self.open()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertNotIn("سؤال اصطناعي أصلي".encode(), response.content)
        self.assertEqual(Case.objects.get().evidence_version, 2)

    @override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True, FATWA_ANSWER_MEDIA_ENABLED=True)
    def test_context_projects_media_metadata_without_opening_or_parsing_originals(self):
        from apps.answer_media.services import save_multipart_answer
        from apps.case_attachments.services import upload

        attachment = upload(
            token=self.receipt["token"],
            raw=b"synthetic attachment",
            filename="evidence.txt",
            media_type="text/plain",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        save_multipart_answer(
            **self.common,
            text="جواب بشري مع مرفق",
            files=[
                {
                    "raw": b"synthetic answer part",
                    "filename": "answer.txt",
                    "media_type": "text/plain",
                }
            ],
            expected_revision=2,
            expected_evidence_version=2,
        )
        with (
            patch(
                "apps.private_media.storage.read_original",
                side_effect=AssertionError("no original I/O in context"),
            ),
            patch(
                "apps.answer_media.services.raw_for_part",
                side_effect=AssertionError("no answer bytes"),
            ),
            patch(
                "apps.case_attachments.services.raw_for_owner",
                side_effect=AssertionError("no attachment bytes"),
            ),
            patch(
                "apps.private_media.validation.validate",
                side_effect=AssertionError("no parser in context"),
            ),
        ):
            result = context.case_workspace(self.request())["mufti_workspace"]
        self.assertEqual(result["manifest"]["part_count"], 2)
        self.assertEqual(result["attachments"][0]["id"], attachment["id"])
        self.assertEqual(result["attachments"][0]["evidence_version"], 2)
        self.assertNotIn("original", result["attachments"][0])
        self.assertNotIn("storage_key", result["attachments"][0])
        self.assertIsNone(result["case"]["answer_manifest"])
        self.assertFalse(result["verification_checked"])

    @override_settings(
        FATWA_CASE_ATTACHMENTS_ENABLED=True,
        FATWA_ANSWER_MEDIA_ENABLED=True,
        FATWA_CASE_CITATIONS_ENABLED=True,
        FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True,
    )
    def test_panels_preserve_case_frame_and_delivery_cookie_cannot_redirect_overview(self):
        page = self.open()
        for action in ("attachment_list", "answer_media", "citations", "pub_open"):
            page = post(
                self.client,
                "/casework/staff/",
                {"action": action, "case_ref": self.receipt["public_ref"]},
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, 'id="mufti-case-reference"')
            self.assertEqual(
                page.context["mufti_workspace"]["case"]["public_ref"], self.receipt["public_ref"]
            )
            self.assertContains(page, 'value="case_workspace"')
        self.client.cookies["fatwa_team_panel"] = "delivery"
        page = self.open(page)
        self.assertContains(page, 'id="mufti-work-heading"')
        self.assertEqual(page.cookies["fatwa_team_panel"].value, "cases")

    def test_csrf_and_duplicate_case_ref_native_forms_remain_rejected(self):
        self.assertEqual(
            self.client.post(
                "/casework/staff/",
                {"action": "case_workspace", "case_ref": self.receipt["public_ref"]},
            ).status_code,
            403,
        )
        body = urlencode(
            [
                ("csrfmiddlewaretoken", hidden(self.queue, "csrfmiddlewaretoken")),
                ("action", "case_workspace"),
                ("case_ref", self.receipt["public_ref"]),
                ("case_ref", self.receipt["public_ref"]),
            ]
        )
        result = self.client.post(
            "/casework/staff/", body, content_type="application/x-www-form-urlencoded"
        )
        self.assertEqual(result.status_code, 400)
        self.assertEqual(CaseEvent.objects.count(), 1)

    @override_settings(FATWA_SOURCE_CASE_INTAKE_ENABLED=True)
    def test_original_source_label_uses_verified_origin_not_website_adapter(self):
        origins = [
            {"evidence_version": 1, "source": "TELEGRAM"},
            {"evidence_version": 2, "source": "WHATSAPP"},
        ]
        with patch("apps.source_case_intake.services.staff_origins", return_value=origins):
            result = context.case_workspace(self.request())["mufti_workspace"]
        self.assertEqual(result["case"]["source_channel"], "WEBSITE")
        self.assertEqual(result["source_label"], "Telegram")
        self.assertTrue(result["source_label_is_origin"])
        with patch("apps.source_case_intake.services.staff_origins", return_value=origins[1:]):
            result = context.case_workspace(self.request())["mufti_workspace"]
        self.assertEqual(result["source_label"], "الموقع")
        self.assertFalse(result["source_label_is_origin"])
