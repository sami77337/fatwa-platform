"""Actual editor roles, immutable sources, independent meaning review and late revocation."""

from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase, override_settings

from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.public_answer_media import services as recording
from apps.public_answer_media.models import RecordingTranscript, TranscriptAction
from tests.casework.test_http import post

from . import transcripts, views
from .test_support import CREDENTIALS
from .transcript_test_support import (
    TEXT,
    TRANSCRIPT_FEATURES,
    TranscriptDomainAuthority,
    TranscriptFixture,
)

BASE = "/casework/operations/"


@override_settings(**TRANSCRIPT_FEATURES)
class OperationalTranscriptTests(TranscriptFixture, TransactionTestCase):
    def test_actual_organizer_editor_admin_review_and_mufti_reader_share_preserved_history(self):
        result = self.save_transcript(
            segments=[
                {
                    "char_start": 0,
                    "char_end": 6,
                    "start_ms": 10,
                    "end_ms": 100,
                }
            ]
        )
        self.assertEqual(result["role"], "ORGANIZER")
        self.assertEqual(result["transcripts"][0]["subject_id"], "operator")
        self.review_transcript()
        row = RecordingTranscript.objects.get(part=self.part)
        with recording.segment_projection(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
            transcript_id=row.pk,
            index=0,
        ) as result:
            self.assertEqual(result["text"], TEXT[:6])
            self.assertEqual(result["start_ms"], 10)
        self.review_transcript(action="WITHDRAW")
        self.assertEqual(
            list(row.actions.order_by("sequence").values_list("action", flat=True)),
            ["REVIEW", "WITHDRAW"],
        )
        self.assertEqual(self.immutable_transcript_sources(), self.transcript_originals)
        with self.assertRaises(cases.CaseConflict):
            cases.save_answer(
                **self.common,
                case_id=self.target["case_id"],
                text="غير مخول",
                expected_revision=3,
                expected_evidence_version=1,
            )

    def test_meaning_approval_requires_actual_mufti_despite_explicit_true_organizer_grants(self):
        self.save_transcript(change_kind="MEANING_REVIEW")
        for subject in ("operator", "admin"):
            with self.subTest(subject=subject), self.assertRaises(cases.CaseConflict):
                self.review_transcript(subject=subject, action="APPROVE_MEANING")
        with self.assertRaises(cases.CaseConflict):
            self.review_transcript(action="REVIEW")
        self.assertFalse(TranscriptAction.objects.exists())
        result = self.review_transcript(subject="mufti", action="APPROVE_MEANING")
        self.assertEqual(result["transcripts"][0]["history"][0]["subject_id"], "mufti")
        self.assertTrue(result["transcripts"][0]["reviewed"])
        self.assertEqual(self.immutable_transcript_sources(), self.transcript_originals)

    def test_editorial_identity_resolution_does_not_widen_original_answer_or_staff_boundary(self):
        self.save_transcript()
        row = RecordingTranscript.objects.get(part=self.part)
        self.directory.identities["mufti"] = replace(
            self.directory.identities["mufti"], role="ORGANIZER_ADMIN"
        )
        with self.assertRaises(cases.CaseConflict):
            with transcripts.projection(**self.common, case_ref=self.target["public_ref"]):
                pass
        with self.assertRaises(cases.CaseConflict):
            with recording.transcript_projection(
                **self.common, case_id=self.target["case_id"], transcript_id=row.pk
            ):
                pass

    def test_actual_roles_do_not_imply_read_edit_review_audio_or_domain_grants(self):
        self.authority.revoke(action="EDIT_RECORDING_TRANSCRIPT")
        with self.assertRaises(cases.CaseConflict):
            self.save_transcript()
        with transcripts.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertFalse(result["parts"][0]["can_edit"])
        with transcripts.save(**{**self.common, "subject_id": "mufti"}, **self.save_values()):
            pass
        self.authority.revoke(subject="admin", action="REVIEW_RECORDING_TRANSCRIPT")
        with self.assertRaises(cases.CaseConflict):
            self.review_transcript()
        self.authority.revoke(action="READ_RECORDING_AUDIO")
        with transcripts.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["transcripts"][0]["text"], TEXT)
            self.assertFalse(result["parts"][0]["can_audio"])
        with self.assertRaises(cases.CaseConflict):
            with transcripts.audio_projection(
                **self.common,
                case_ref=self.target["public_ref"],
                part_id=self.part.pk,
                part_sha256=self.part.sha256,
            ):
                pass
        self.domain.denied.add(("operator", "READ_TRANSCRIPT"))
        with transcripts.projection(**self.common, case_ref=self.target["public_ref"]) as result:
            self.assertEqual(result["parts"], [])
            self.assertEqual(result["transcripts"], [])

    def test_defaults_hidden_scope_and_missing_current_policies_are_closed(self):
        for name, value in (
            ("FATWA_OPERATIONAL_TRANSCRIPTS_ENABLED", False),
            ("FATWA_PUBLIC_ANSWER_MEDIA_ENABLED", False),
            ("FATWA_ANSWER_MEDIA_ENABLED", False),
            ("FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY", None),
            ("FATWA_RESEARCH_WORKSPACE_RIGHTS", None),
        ):
            with (
                self.subTest(name=name),
                override_settings(**{name: value}),
                self.assertRaises(cases.CaseConflict),
            ):
                self.save_transcript()
        for kind in ("hidden", "unscoped"):
            with self.assertRaises(cases.CaseConflict):
                self.save_transcript(case_ref=self.receipts[kind]["public_ref"])
        self.assertEqual(self.state(), self.originals)

    def test_revision_source_and_explicit_segment_pins_cannot_be_forged(self):
        for changes in (
            {"part_sha256": "0" * 64},
            {"expected_revision": 2},
            {"expected_evidence_version": 2},
            {"expected_version": 1},
            {"text": ""},
            {"change_kind": "APPROVED"},
            {"segments": [{"char_start": 0, "char_end": 6, "start_ms": 0, "end_ms": 6001}]},
            {"segments": [{"char_start": 0, "char_end": 1000, "start_ms": 0, "end_ms": 100}]},
        ):
            with self.subTest(changes=changes), self.assertRaises(cases.CaseConflict):
                self.save_transcript(**changes)
        self.assertEqual(self.state(), self.originals)

    def test_replay_and_review_cas_keep_versions_and_independent_review(self):
        values = self.save_values()
        for _ in range(2):
            with transcripts.save(**self.common, **values):
                pass
        self.assertEqual(RecordingTranscript.objects.count(), 1)
        with self.assertRaises(cases.CaseConflict):
            with transcripts.save(**self.common, **{**values, "text": "تغيير بنفس الأمر"}):
                pass
        with self.assertRaises(cases.CaseConflict):
            self.review_transcript(subject="operator")
        with self.assertRaises(cases.CaseConflict):
            self.review_transcript(expected_actions=1)
        values = self.review_values()
        for _ in range(2):
            with transcripts.decide(**{**self.common, "subject_id": "admin"}, **values):
                pass
        self.assertEqual(TranscriptAction.objects.count(), 1)
        self.save_transcript(text="نسخة تحريرية ثانية محفوظة")
        self.assertEqual(RecordingTranscript.objects.count(), 2)
        self.assertEqual(self.immutable_transcript_sources(), self.transcript_originals)

    def test_late_audio_and_operational_revocation_reject_already_assembled_bytes(self):
        values = dict(
            self.common,
            case_ref=self.target["public_ref"],
            part_id=self.part.pk,
            part_sha256=self.part.sha256,
        )
        for kind in ("media", "operational"):
            rules = set(self.authority.transcript_rules)
            with self.subTest(kind=kind), self.assertRaises(cases.CaseConflict):
                with transcripts.audio_projection(**values) as result:
                    self.assertTrue(result["raw"])
                    if kind == "media":
                        self.rights.denied.add("operator")
                    else:
                        self.authority.revoke(action="READ_RECORDING_AUDIO")
            self.authority.transcript_rules = rules
            self.rights.denied.clear()
        self.assertEqual(self.state(), self.originals)

    def test_late_policy_replacement_and_real_editor_revocation_roll_back_append(self):
        original = settings.FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY
        try:
            with self.assertRaises(cases.CaseConflict):
                with transcripts.save(**self.common, **self.save_values()):
                    replacement = TranscriptDomainAuthority()
                    replacement.rules = set(original.rules)
                    settings.FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY = replacement
        finally:
            settings.FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY = original
        self.assertEqual(self.state(), self.originals)
        actor = self.directory.identities["operator"]
        try:
            with self.assertRaises(cases.CaseConflict):
                with transcripts.save(**self.common, **self.save_values()):
                    self.directory.identities["operator"] = replace(actor, active=False)
        finally:
            self.directory.identities["operator"] = actor
        self.assertEqual(self.state(), self.originals)

    def test_unrelated_callback_append_cannot_hide_in_expected_transcript_append(self):
        triggered = False

        def hook(values):
            nonlocal triggered
            if not triggered and RecordingTranscript.objects.filter(part=self.part).exists():
                triggered = True
                organization.save(
                    case_id=self.target["case_id"],
                    subject_id="mufti",
                    provider=self.directory,
                    tags=[],
                    question_types=[],
                    note="تغيير جانبي يجب أن يرفض الطلب",
                    command_id=self.save_values()["command_id"],
                    expected_metadata_version=0,
                    expected_revision=3,
                    expected_evidence_version=1,
                    synthetic_fixtures_only=True,
                )

        self.domain.hook = hook
        with self.assertRaises(cases.CaseConflict):
            self.save_transcript()
        self.domain.hook = None
        self.assertTrue(triggered)
        self.assertEqual(self.state(), self.originals)

    def login(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="127.0.0.1")
        page = client.get(BASE + "login/")
        response = post(client, BASE + "login/", {"credential": CREDENTIALS["operator"]}, page)
        self.assertEqual(response.status_code, 303)
        return client, client.get(BASE)

    def test_native_csrf_editor_form_exact_audio_and_render_revocation(self):
        client, page = self.login()
        page = post(
            client,
            BASE,
            {"action": "transcript_editor", "case_ref": self.target["public_ref"]},
            page,
        )
        self.assertEqual(page.status_code, 200)
        data = {
            "action": "transcript_save",
            "case_ref": self.target["public_ref"],
            "part_id": str(self.part.pk),
            "part_sha256": self.part.sha256,
            "text": TEXT,
            "change_kind": "EDITORIAL",
            "note": "تحرير من نموذج المنظم",
            "version": "0",
            "command_id": self.save_values()["command_id"],
            "revision": "3",
            "evidence_version": "1",
        }
        self.assertEqual(client.post(BASE, data, HTTP_HOST="127.0.0.1").status_code, 403)
        self.assertEqual(post(client, BASE, {**data, "role": "MUFTI"}, page).status_code, 409)
        saved = post(client, BASE, data, page)
        self.assertEqual(saved.status_code, 200)
        self.assertContains(saved, 'id="ops-transcript-saved"')
        audio = post(
            client,
            BASE,
            {
                "action": "transcript_audio",
                "case_ref": self.target["public_ref"],
                "part_id": str(self.part.pk),
                "part_sha256": self.part.sha256,
            },
            page,
        )
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio["Content-Type"], "audio/wav")
        self.assertNotIn("private-original", audio["Content-Disposition"])
        before = self.state()
        actual_render = views.render

        def render_and_revoke(*args, **kwargs):
            response = actual_render(*args, **kwargs)
            self.authority.revoke(action="EDIT_RECORDING_TRANSCRIPT")
            return response

        with patch.object(views, "render", side_effect=render_and_revoke):
            response = post(
                client,
                BASE,
                {**data, "version": "1", "command_id": self.save_values()["command_id"]},
                page,
            )
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(TEXT.encode(), response.content)
        self.assertEqual(self.state(), before)
