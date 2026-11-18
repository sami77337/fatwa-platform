"""Current-case evidence/media navigation uses canonical versions and existing HTTP guards."""

from dataclasses import replace
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings

from apps.answer_media import services as media
from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.private_media.fixtures import synthetic_files
from tests.casework.test_http import hidden, post

from . import context
from . import tests as fixtures


@override_settings(
    FATWA_MUFTI_WORKSPACE_ENABLED=True,
    FATWA_CASEWORK_WEB_ENABLED=True,
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_ANSWER_MEDIA_ENABLED=True,
)
class ConnectedJourneyTests(TransactionTestCase):
    setUp = fixtures.MuftiWorkspaceTests.setUp
    open = fixtures.MuftiWorkspaceTests.open
    mutation = fixtures.MuftiWorkspaceTests.mutation
    request = fixtures.MuftiWorkspaceTests.request

    def upload(self, name):
        name, mime, raw = next(row for row in synthetic_files() if row[0] == name)
        case = Case.objects.get(pk=self.receipt["case_id"])
        result = attachments.upload(
            token=self.receipt["token"],
            raw=raw,
            filename=name,
            media_type=mime,
            expected_revision=case.revision,
            synthetic_fixtures_only=True,
        )
        return result, raw

    def test_evidence_history_groups_original_files_and_answer_basis_without_new_records(self):
        picture, _ = self.upload("synthetic.png")
        page = self.mutation(self.open(), "draft", text="جواب على الوقائع الثانية")
        audio, _ = self.upload("synthetic.wav")
        before = CaseEvent.objects.count()
        page = self.open(page)
        self.assertEqual(page.status_code, 200)
        rows = page.context["mufti_workspace"]["evidence_history"]
        self.assertEqual([r["version"] for r in rows], [1, 2, 3])
        self.assertEqual(rows[0]["text"], "سؤال اصطناعي أصلي كما وصل")
        self.assertEqual(rows[0]["attachments"], [])
        self.assertEqual([a["id"] for a in rows[1]["attachments"]], [picture["id"]])
        self.assertEqual(rows[1]["answer_revisions"], [1])
        self.assertFalse(rows[1]["newer_than_answer"])
        self.assertTrue(rows[2]["newer_than_answer"])
        self.assertTrue(rows[2]["current"])
        self.assertEqual([a["id"] for a in rows[2]["attachments"]], [audio["id"]])
        self.assertContains(page, 'id="mufti-evidence-history"')
        self.assertContains(page, 'data-evidence-version="3"')
        self.assertContains(page, "أُضيفت بعد أساس أحدث جواب")
        self.assertEqual(CaseEvent.objects.count(), before)
        self.assertEqual(Case.objects.count(), 1)

    def test_actual_image_pdf_audio_previews_require_current_scope(self):
        uploaded = [
            self.upload(name) for name in ("synthetic.png", "synthetic.pdf", "synthetic.wav")
        ]
        page = self.open()
        self.assertContains(page, '<img loading="lazy"')
        self.assertContains(page, '<iframe sandbox loading="lazy"')
        self.assertContains(page, '<audio controls preload="none"')
        for row, raw in uploaded:
            url = f"/casework/staff/attachments/{row['id']}/"
            self.assertContains(page, url)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, raw)
            self.assertIn("no-store", response["Cache-Control"])
        self.directory.current = replace(self.directory.current, case_keys=frozenset({"unrelated"}))
        for row, raw in uploaded:
            response = self.client.get(f"/casework/staff/attachments/{row['id']}/")
            self.assertIn(response.status_code, (403, 404))
            self.assertNotEqual(response.content, raw)

    def test_multipart_handoff_edits_text_preserving_parts_and_old_answer(self):
        media.save_multipart_answer(
            **self.common,
            text="نص بشري أول",
            files=[dict(raw=b"synthetic original", filename="answer.txt", media_type="text/plain")],
            expected_revision=1,
            expected_evidence_version=1,
        )
        before = media.staff_snapshot(**self.common)["latest_package"]
        page = self.open()
        self.assertContains(page, 'id="mufti-multipart-edit"')
        self.assertNotContains(page, 'id="answer-text"')
        self.assertNotContains(page, 'name="action" value="draft"')
        editor = post(
            self.client,
            "/casework/staff/",
            {
                "action": "answer_media",
                "case_ref": self.receipt["public_ref"],
            },
            page,
        )
        self.assertEqual(editor.status_code, 200)
        self.assertContains(editor, "نص بشري أول")
        current = editor.context["selected"]
        changed = self.client.post(
            "/casework/staff/",
            {
                "csrfmiddlewaretoken": hidden(editor, "csrfmiddlewaretoken"),
                "action": "answer_media_save",
                "case_ref": self.receipt["public_ref"],
                "revision": str(current["revision"]),
                "evidence_version": str(current["evidence_version"]),
                "text": "نص بشري منقح",
                "retain": "yes",
                "synthetic_only": "yes",
            },
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        after = media.staff_snapshot(**self.common)["latest_package"]
        self.assertEqual(after["answer_revision"], 2)
        self.assertEqual(after["parts"][1]["sha256"], before["parts"][1]["sha256"])
        self.assertEqual(after["parts"][1]["filename"], "answer.txt")
        self.assertEqual(Case.objects.get().answers.count(), 2)
        self.assertEqual(
            Case.objects.get().answers.order_by("revision").first().text, "نص بشري أول"
        )

    def test_server_authorized_publication_and_knowledge_context_cannot_be_overridden(self):
        for action, attribute in (
            ("pub_read", "publication_authorized_case_ref"),
            ("knowledge_browse", "knowledge_authorized_case_ref"),
        ):
            with self.subTest(action=action):
                request = self.request(
                    fields={"action": action, "publication_id": "identifier-only"}
                )
                self.assertEqual(context.case_workspace(request), {})
                setattr(request, attribute, self.receipt["public_ref"])
                result = context.case_workspace(request)["mufti_workspace"]
                self.assertEqual(result["case"]["public_ref"], self.receipt["public_ref"])
                self.assertEqual(result["active"], "publication")
                request.POST = request.POST.copy()
                request.POST["case_ref"] = "FT-2026-" + "A" * 20
                with self.assertRaises(cases.CaseConflict):
                    context.case_workspace(request)
        request = self.request(
            fields={"action": "pub_create", "case_ref": self.receipt["public_ref"]}
        )
        request.publication_authorized_case_ref = self.receipt["public_ref"]
        self.assertEqual(
            context.case_workspace(request)["mufti_workspace"]["active"], "publication"
        )
        request.POST = request.POST.copy()
        request.POST.pop("case_ref")
        with self.assertRaises(cases.CaseConflict):
            context.case_workspace(request)
        request = self.request(fields={"action": "draft"})
        request.publication_authorized_case_ref = self.receipt["public_ref"]
        with self.assertRaises(cases.CaseConflict):
            context.case_workspace(request)

    @override_settings(
        FATWA_SOURCE_RIGHTS_ENABLED=True,
        FATWA_RESEARCH_WORKSPACE_ENABLED=True,
        FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True,
        FATWA_COMPOSITE_DELIVERY_ENABLED=True,
        FATWA_PILOT_WORKBENCH_ENABLED=True,
    )
    def test_navigation_is_same_case_read_only_and_waiting_has_no_edit_shortcut(self):
        page = self.open()
        groups = page.context["mufti_workspace"]["journey"]
        actions = {a["action"] for group in groups for a in group["actions"]}
        self.assertTrue(
            {"rights_desk", "research_open", "pub_open", "composite_open", "pilot_open"} <= actions
        )
        self.assertFalse(
            {"approve", "answer_media_release", "pilot_authorize", "pub_approve"} & actions
        )
        self.assertContains(page, 'id="mufti-connected-journey"')
        before = CaseEvent.objects.count()
        request = self.request()
        with patch(
            "apps.private_media.storage.read_original", side_effect=AssertionError("no bytes")
        ):
            context.case_workspace(request)
        self.assertEqual(CaseEvent.objects.count(), before)
        page = self.mutation(page, "clarify", text="يرجى توضيح الواقعة")
        groups = page.context["mufti_workspace"]["journey"]
        answer_group = next(g for g in groups if g["key"] == "answer")
        self.assertEqual([a["fragment"] for a in answer_group["actions"]], ["review"])
        with override_settings(FATWA_RESEARCH_WORKSPACE_ENABLED=False):
            result = context.case_workspace(self.request())["mufti_workspace"]
        self.assertNotIn(
            "research_open", {a["action"] for g in result["journey"] for a in g["actions"]}
        )
