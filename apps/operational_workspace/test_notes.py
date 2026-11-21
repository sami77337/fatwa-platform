"""Real operational note writes, exact current grants and immutable source protection."""

import copy
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.case_organization import services as organization
from apps.case_organization.models import OrganizationRevision
from apps.casework import services as cases
from apps.casework.models import Case
from tests.casework.test_http import hidden, post

from . import notes, services, views
from .notes_test_support import NOTE_FEATURES, NoteFixture
from .test_support import CREDENTIALS

BASE = "/casework/operations/"


@override_settings(**NOTE_FEATURES)
class OperationalNoteTests(NoteFixture, TransactionTestCase):
    def test_actual_organizer_append_preserves_tags_types_approved_answer_and_source(self):
        prior = OrganizationRevision.objects.get(case_id=self.target["case_id"])
        result = self.append_note()
        rows = list(
            OrganizationRevision.objects.filter(case_id=self.target["case_id"]).order_by("version")
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].tags, prior.tags)
        self.assertEqual(rows[1].question_types, prior.question_types)
        self.assertEqual(rows[1].subject_id, "operator")
        self.assertEqual(rows[1].provider_id, self.directory.provider_id)
        self.assertEqual(result["history"][0]["note"], rows[1].note)
        self.assertEqual(result["role"], "ORGANIZER")
        self.assertEqual(self.immutable_state(), self.note_originals)
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.common,
                case_id=self.target["case_id"],
                text="غير مخول",
                expected_revision=3,
                expected_evidence_version=1,
            )
        self.assertEqual(self.immutable_state(), self.note_originals)

    def test_read_and_add_are_independent_and_queue_reads_never_disclose_notes(self):
        grants = set(self.authority.grants)
        self.authority.revoke(action="READ_INTERNAL_NOTES")
        result = self.append_note()
        self.assertEqual(result["history"], [])
        self.assertFalse(result["can_read"])
        self.assertTrue(result["can_add"])
        with services.queue_projection(**self.common) as queue:
            self.assertNotIn("ملاحظة", str(queue))
        self.authority.revoke(action="ADD_INTERNAL_NOTE")
        with self.assertRaises(cases.CaseConflict):
            with notes.projection(case_ref=self.target["public_ref"], **self.common):
                pass
        self.authority.grants = set(grants)
        self.authority.revoke(action="ADD_INTERNAL_NOTE")
        with notes.projection(case_ref=self.target["public_ref"], **self.common) as read_only:
            self.assertTrue(read_only["can_read"])
            self.assertFalse(read_only["can_add"])
            self.assertEqual(len(read_only["history"]), 2)
        with self.assertRaises(cases.CaseConflict):
            self.append_note()
        self.assertEqual(self.immutable_state(), self.note_originals)

    def test_current_grants_scope_and_default_off_are_required_for_every_replay(self):
        values = self.note_values()
        with notes.append(**self.common, **values):
            pass
        before = self.state()
        self.authority.revoke(action="ADD_INTERNAL_NOTE")
        with self.assertRaises(cases.CaseConflict):
            with notes.append(**self.common, **values):
                pass
        for key in ("hidden", "unscoped"):
            with self.assertRaises(cases.CaseConflict):
                with notes.projection(case_ref=self.receipts[key]["public_ref"], **self.common):
                    pass
        for flag in ("FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED", "FATWA_CASE_ORGANIZATION_ENABLED"):
            with override_settings(**{flag: False}), self.assertRaises(cases.CaseConflict):
                with notes.projection(case_ref=self.target["public_ref"], **self.common):
                    pass
        self.assertEqual(self.state(), before)

    def test_exact_retry_after_later_metadata_is_idempotent_conflicts_keep_original_note(self):
        values = self.note_values()
        with notes.append(**self.common, **values):
            pass
        case = Case.objects.get(pk=self.target["case_id"])
        organization.save(
            case_id=str(case.pk),
            subject_id="mufti",
            provider=self.directory,
            tags=["تحديث وسم مستقل"],
            question_types=["TIME"],
            note="",
            command_id=uuid.uuid4(),
            expected_metadata_version=2,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            synthetic_fixtures_only=True,
        )
        before = self.state()
        with notes.append(**self.common, **values) as repeated:
            self.assertTrue(repeated["saved"])
            self.assertEqual(repeated["metadata_version"], 3)
        self.assertEqual(self.state(), before)
        with self.assertRaises(cases.CaseConflict):
            with notes.append(**self.common, **{**values, "note": "بديل لنفس الأمر"}):
                pass
        for field in (
            "expected_metadata_version",
            "expected_revision",
            "expected_evidence_version",
        ):
            with self.assertRaises(cases.CaseConflict):
                self.append_note(**{field: 0 if field == "expected_metadata_version" else 999})
        self.assertEqual(self.state(), before)

    def test_invalid_text_and_exhausted_history_never_write(self):
        before = self.state()
        for value in ("", "  ", "x" * 2001, "a\x00b", None):
            with self.assertRaises(cases.CaseConflict):
                self.append_note(note=value)
        for version in (True, -1, 256, "1"):
            with self.assertRaises(cases.CaseConflict):
                self.append_note(expected_metadata_version=version)
        self.assertEqual(self.state(), before)

    def test_unrelated_callback_append_is_not_adopted_in_authorized_write_watermark(self):
        def changing(values):
            if values["action"] != "ADD_INTERNAL_NOTE":
                return
            self.authority.hook = None
            target = Case.objects.get(pk=self.receipts["metadata"]["case_id"])
            organization.save(
                case_id=str(target.pk),
                subject_id="mufti",
                provider=self.directory,
                tags=["تغيير غير متعلق"],
                question_types=[],
                note="",
                command_id=uuid.uuid4(),
                expected_metadata_version=0,
                expected_revision=target.revision,
                expected_evidence_version=target.evidence_version,
                synthetic_fixtures_only=True,
            )

        self.authority.hook = changing
        with self.assertRaises(cases.CaseConflict):
            self.append_note()
        self.assertEqual(self.state(), self.originals)

    def test_final_revocation_rolls_back_actual_note_and_discards_read_result(self):
        with self.assertRaises(cases.CaseConflict):
            with notes.append(**self.common, **self.note_values()):
                self.authority.revoke(action="ADD_INTERNAL_NOTE")
        self.assertEqual(self.state(), self.originals)


@override_settings(**NOTE_FEATURES)
class OperationalNoteHTTPTests(NoteFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )

    def open_notes(self):
        page = self.client.get(BASE + "login/")
        response = post(self.client, BASE + "login/", {"credential": CREDENTIALS["operator"]}, page)
        self.assertEqual(response.status_code, 303, response.content)
        page = self.client.get(BASE)
        self.assertContains(page, "الملاحظات الداخلية")
        response = post(
            self.client, BASE, {"action": "notes", "case_ref": self.target["public_ref"]}, page
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def fields(self, page):
        return {
            key: hidden(page, key)
            for key in (
                "action",
                "case_ref",
                "revision",
                "evidence_version",
                "metadata_version",
                "command_id",
            )
        } | {"note": "نص داخلي <script>خاص</script>"}

    def test_native_note_form_escapes_text_replays_without_duplicates_and_preserves_source(self):
        page = self.open_notes()
        fields = self.fields(page)
        response = post(self.client, BASE, fields, page)
        self.assertContains(response, 'id="ops-note-saved"')
        self.assertContains(response, "&lt;script&gt;خاص&lt;/script&gt;")
        self.assertNotContains(response, "<script>خاص</script>")
        self.assertContains(response, "ملاحظة داخلية لا تعرضها قائمة التشغيل")
        self.assertNotContains(response, 'name="tags"')
        self.assertNotContains(response, 'name="answer"')
        self.assertEqual(
            OrganizationRevision.objects.filter(case_id=self.target["case_id"]).count(), 2
        )
        repeated = post(self.client, BASE, fields, page)
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(
            OrganizationRevision.objects.filter(case_id=self.target["case_id"]).count(), 2
        )
        self.assertEqual(self.immutable_state(), self.note_originals)
        self.assertIn("no-store", response["Cache-Control"])
        requester = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        status_page = requester.get("/casework/status/")
        unlocked = post(
            requester,
            "/casework/status/",
            {"action": "unlock", "token": self.target["token"]},
            status_page,
        )
        self.assertEqual(unlocked.status_code, 303, unlocked.content)
        status = requester.get("/casework/status/")
        self.assertEqual(status.status_code, 200, status.content)
        self.assertNotContains(status, "نص داخلي")
        self.assertNotContains(status, "ملاحظة داخلية لا تعرضها قائمة التشغيل")

    def test_add_only_read_only_csrf_unknown_and_duplicate_fields_do_not_expand_access(self):
        self.authority.revoke(action="READ_INTERNAL_NOTES")
        page = self.open_notes()
        self.assertNotContains(page, "ملاحظة داخلية لا تعرضها قائمة التشغيل")
        self.assertContains(page, 'id="ops-notes-unreadable"')
        fields = self.fields(page)
        self.assertEqual(self.client.post(BASE, fields).status_code, 403)
        for extra in ({"tags": "تعديل"}, {"role": "MUFTI"}, {"note": ["أ", "ب"]}):
            response = self.client.post(
                BASE,
                {**fields, **extra, "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken")},
            )
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.state(), self.originals)
        response = post(self.client, BASE, fields, page)
        self.assertContains(response, 'id="ops-note-saved"')
        self.assertNotContains(response, "نص داخلي")
        self.assertNotContains(response, "ملاحظة داخلية لا تعرضها قائمة التشغيل")

    def test_final_native_render_trust_changes_discard_body_and_roll_back_note(self):
        page = self.open_notes()
        render = views.render
        old_directory = settings.FATWA_CASEWORK_IDENTITY_PROVIDER
        old_grants = set(self.authority.grants)
        for kind in ("read", "add", "feature", "directory", "source"):

            def changed(*args, **kwargs):
                response = render(*args, **kwargs)
                if kind == "read":
                    self.authority.revoke(action="READ_INTERNAL_NOTES")
                elif kind == "add":
                    self.authority.revoke(action="ADD_INTERNAL_NOTE")
                elif kind == "feature":
                    settings.FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED = False
                elif kind == "directory":
                    settings.FATWA_CASEWORK_IDENTITY_PROVIDER = copy.copy(old_directory)
                else:
                    case = Case.objects.get(pk=self.target["case_id"])
                    organization.save(
                        case_id=str(case.pk),
                        subject_id="mufti",
                        provider=self.directory,
                        tags=["تغيير بعد التصيير"],
                        question_types=[],
                        note="",
                        command_id=uuid.uuid4(),
                        expected_metadata_version=2,
                        expected_revision=case.revision,
                        expected_evidence_version=case.evidence_version,
                        synthetic_fixtures_only=True,
                    )
                return response

            with self.subTest(kind=kind):
                try:
                    with patch.object(views, "render", side_effect=changed):
                        response = post(self.client, BASE, self.fields(page), page)
                    self.assertEqual(response.status_code, 409, response.content)
                    self.assertNotContains(response, "نص داخلي", status_code=409)
                    self.assertEqual(self.state(), self.originals)
                finally:
                    self.authority.grants = set(old_grants)
                    settings.FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED = True
                    settings.FATWA_CASEWORK_IDENTITY_PROVIDER = old_directory
