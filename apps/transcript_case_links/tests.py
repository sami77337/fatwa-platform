"""Focused PostgreSQL behavior and native-form journey on actual case services."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseEvidence, CaseSource
from apps.fast8_transcript_queue.workbench.services import checkpoint, export_bundle, open_document
from tests.casework.test_core import TestDirectory
from tests.casework.test_http import Directory, hidden, post

from . import services as links
from .models import TranscriptLink, TranscriptUpload


def new_case():
    key = secrets.token_hex(12)
    return cases.intake_case(
        original_question="  أصل سؤال الموقع الاصطناعي\r\nكما وصل  ",
        source_event_id=key,
        requester_id="rq-" + key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )


def bundle():
    raw = (
        Path(__file__).resolve().parents[2]
        / "tools/transcript_pipeline/examples/synthetic-manual.json"
    ).read_bytes()
    return export_bundle(open_document(raw, ".json", synthetic_fixtures_only=True))


def common(receipt, provider=None):
    return dict(
        case_id=receipt["case_id"],
        subject_id="synthetic-mufti",
        provider=provider or TestDirectory([receipt["public_ref"]]),
        synthetic_fixtures_only=True,
    )


def staged(receipt):
    return links.preview(**common(receipt), bundle=bundle())


def attach(receipt, preview):
    return links.attach(
        **common(receipt),
        upload_id=preview["upload_id"],
        external_id=preview["entries"][0].external_id,
    )


class BindingTests(TransactionTestCase):
    def test_v2_multi_question_bundle_binds_only_explicit_selected_question(self):
        from apps.fast8_transcript_queue.workbench.services import relink_answer, restore_bundle

        source = restore_bundle(bundle(), synthetic_fixtures_only=True)
        data = json.loads(source.current)
        question, answer = data["items"]
        data["items"].extend(
            [
                dict(
                    question,
                    segment_id="question-2",
                    pair_id="pair-2",
                    start_ms=2000,
                    end_ms=3000,
                    text="  السؤال الثاني الاصطناعي\r\nبحروفه  ",
                ),
                dict(
                    answer,
                    segment_id="answer-2",
                    pair_id="orphan",
                    start_ms=3000,
                    end_ms=4000,
                    text="جواب مصدر ثانٍ لا يُستورد كفتوى",
                ),
            ]
        )
        document = open_document(json.dumps(data).encode(), ".json", synthetic_fixtures_only=True)
        document = relink_answer(document, index=3, question_index=2)
        receipt = new_case()
        preview = links.preview(**common(receipt), bundle=export_bundle(document))
        selected = preview["entries"][1]
        links.attach(
            **common(receipt), upload_id=preview["upload_id"], external_id=selected.external_id
        )
        self.assertEqual(
            CaseEvidence.objects.get(version=2).text, "  السؤال الثاني الاصطناعي\r\nبحروفه  "
        )
        self.assertEqual(links.read_links(**common(receipt))[0]["entry"].pair_id, "pair-2")
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_durable_evidence_invalidates_approval_without_importing_source_answer(self):
        receipt = new_case()
        draft = cases.save_answer(
            **common(receipt),
            text="مسودة بشرية اصطناعية",
            expected_revision=1,
            expected_evidence_version=1,
        )
        approved = cases.record_decision(
            **common(receipt),
            answer_id=draft["answers"][0]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        preview = staged(receipt)
        self.assertEqual(Case.objects.get().revision, approved["revision"])
        self.assertEqual(TranscriptLink.objects.count(), 0)
        result = attach(receipt, preview)
        self.assertTrue(result["created"])
        current = cases.read_case(**common(receipt))
        self.assertEqual((current["status"], current["evidence_version"]), ("UNDER_REVIEW", 2))
        self.assertIsNone(current["approved_answer_id"])
        self.assertEqual(current["original_question"], "  أصل سؤال الموقع الاصطناعي\r\nكما وصل  ")
        self.assertEqual(CaseSource.objects.get().channel, "WEBSITE")
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(
            CaseEvidence.objects.get(version=2).text, preview["entries"][0].question.text
        )
        self.assertEqual(
            CaseEvent.objects.order_by("sequence").last().subject_id, "synthetic-mufti"
        )
        connections.close_all()
        self.assertEqual(
            links.read_links(**common(receipt))[0]["entry"].answer.text,
            preview["entries"][0].answer.text,
        )
        public = cases.requester_status(receipt["token"], synthetic_fixtures_only=True)
        self.assertNotIn("original_question", public)
        self.assertNotIn(preview["entries"][0].answer.text, str(public))
        with self.assertRaises(cases.CaseConflict):
            cases.record_decision(
                **common(receipt),
                answer_id=draft["answers"][0]["id"],
                action="APPROVE",
                expected_revision=current["revision"],
                expected_evidence_version=2,
            )

    def test_replay_and_concurrent_confirm_only_append_once(self):
        receipt, preview = new_case(), None
        preview = staged(receipt)

        def confirm(_):
            connections.close_all()
            try:
                return attach(receipt, preview)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm, range(2)))
        self.assertCountEqual([r["created"] for r in results], [True, False])
        self.assertEqual(TranscriptLink.objects.count(), 1)
        self.assertEqual(CaseEvidence.objects.count(), 2)
        self.assertEqual(Case.objects.get().revision, 2)

    def test_cross_case_role_epoch_and_unacknowledged_calls_cannot_bind(self):
        a, b = new_case(), new_case()
        preview = staged(a)
        for args in (
            common(b),
            common(a, TestDirectory([b["public_ref"]])),
            common(a, TestDirectory([a["public_ref"]], role="ORGANIZER_ADMIN")),
            common(a, TestDirectory([a["public_ref"]], epoch="new-epoch")),
            {**common(a), "synthetic_fixtures_only": False},
        ):
            with (
                self.subTest(provider=type(args["provider"]).__name__),
                self.assertRaises(cases.CaseConflict),
            ):
                links.attach(
                    **args,
                    upload_id=preview["upload_id"],
                    external_id=preview["entries"][0].external_id,
                )
        self.assertEqual(TranscriptLink.objects.count(), 0)
        self.assertEqual(CaseEvidence.objects.count(), 2)

    def test_stale_preview_and_pending_clarification_cannot_change_facts(self):
        receipt = new_case()
        preview = staged(receipt)
        cases.request_clarification(
            **common(receipt),
            text="استيضاح اصطناعي مطلوب من السائل",
            expected_revision=1,
            expected_evidence_version=1,
        )
        with self.assertRaises(cases.CaseConflict):
            attach(receipt, preview)
        fresh = staged(receipt)
        with self.assertRaisesRegex(cases.CaseConflict, "requester_clarification_still_required"):
            attach(receipt, fresh)
        self.assertEqual(Case.objects.get().stage, "NEEDS_CLARIFICATION")
        self.assertEqual(CaseEvidence.objects.count(), 1)

    def test_atomic_failure_and_postgres_immutability_cross_case_guards(self):
        a, b = new_case(), new_case()
        preview = staged(a)
        with patch.object(TranscriptLink.objects, "create", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                attach(a, preview)
        self.assertEqual(Case.objects.get(pk=a["case_id"]).revision, 1)
        self.assertEqual(CaseEvent.objects.filter(case_id=a["case_id"]).count(), 1)
        attach(a, preview)
        link = TranscriptLink.objects.get()
        for model, fields in (
            (TranscriptUpload, {"sha256": "0" * 64}),
            (TranscriptLink, {"case_id": b["case_id"]}),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.update(**fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TranscriptLink.objects.create(
                case_id=b["case_id"],
                upload=link.upload,
                evidence=link.evidence,
                event=link.event,
                external_id="other",
                question_sha256=link.question_sha256,
            )

    def test_invalid_or_incomplete_bundle_has_no_preview_or_case_effect(self):
        receipt = new_case()
        from apps.fast8_transcript_queue.workbench.services import restore_bundle

        doc = restore_bundle(bundle(), synthetic_fixtures_only=True)
        data = json.loads(doc.current)
        data["items"][1]["start_ms"] = 999
        unfinished = checkpoint(
            open_document(json.dumps(data).encode(), ".json", synthetic_fixtures_only=True)
        )
        for raw in (b"not-zip", b"x" * (links.MAX_BUNDLE + 1), unfinished):
            with self.assertRaises(cases.CaseConflict):
                links.preview(**common(receipt), bundle=raw)
        self.assertEqual(TranscriptUpload.objects.count(), 0)
        self.assertEqual(Case.objects.get().revision, 1)

    def test_populated_guard_migration_roundtrip_preserves_binding(self):
        receipt = new_case()
        preview = staged(receipt)
        attach(receipt, preview)
        connection = connections["default"]
        try:
            MigrationExecutor(connection).migrate([("transcript_case_links", "0001_initial")])
            self.assertEqual(TranscriptLink.objects.count(), 1)
        finally:
            MigrationExecutor(connection).migrate(
                [("transcript_case_links", "0002_binding_guards")]
            )
        self.assertEqual(links.read_links(**common(receipt))[0]["version"], 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TranscriptUpload.objects.update(bundle=b"changed")


@override_settings(FATWA_CASEWORK_WEB_ENABLED=True)
class BindingHTTPTests(TransactionTestCase):
    def test_transcript_navigation_returns_from_delivery_to_guarded_case_editor(self):
        page = self.login()
        self.assertEqual(
            post(self.client, "/casework/staff/", {"action": "journey_delivery"}, page).status_code,
            303,
        )
        page = self.client.get("/casework/staff/")
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "transcript_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertContains(page, "ربط سؤال من تفريغ")
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertContains(page, 'id="answer-text"')
        self.assertNotContains(page, 'id="prepare-form"')

    def setUp(self):
        self.client = Client(
            enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
        )
        self.receipt = new_case()
        self.directory = Directory()
        self.directory.grant(self.receipt["public_ref"])
        self.configured = override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory)
        self.configured.enable()
        self.addCleanup(self.configured.disable)

    def login(self):
        page = self.client.get("/casework/staff/login/")
        result = post(
            self.client, "/casework/staff/login/", {"credential": self.directory.credential}, page
        )
        self.assertEqual(result.status_code, 303)
        return self.client.get("/casework/staff/")

    def test_actual_upload_preview_confirm_and_reopen_in_shared_staff_journey(self):
        page = self.login()
        self.assertContains(page, "ربط التفريغات بالقضايا")
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "transcript_open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        page = self.client.post(
            "/casework/staff/",
            {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "action": "transcript_preview",
                "case_ref": self.receipt["public_ref"],
                "synthetic_only": "yes",
                "bundle": SimpleUploadedFile("review.zip", bundle()),
            },
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(Case.objects.get().evidence_version, 1)
        page = post(
            self.client,
            "/casework/staff/",
            {
                "action": "transcript_attach",
                "case_ref": self.receipt["public_ref"],
                "upload_id": hidden(page, "upload_id"),
                "external_id": hidden(page, "external_id"),
                "confirm": "yes",
            },
            page,
        )
        self.assertEqual(page.status_code, 200, page.content)
        self.assertContains(page, "الروابط المحفوظة (1)")
        page = post(
            self.client,
            "/casework/staff/",
            {"action": "open", "case_ref": self.receipt["public_ref"]},
            page,
        )
        self.assertContains(page, links._entries(bundle())[0].question.text)
        self.assertNotContains(page, links._entries(bundle())[0].answer.text)
        self.assertIn("no-store", page["Cache-Control"])

    def test_csrf_anonymous_foreign_case_and_large_file_are_denied(self):
        self.assertEqual(
            self.client.post("/casework/staff/", {"action": "transcripts"}).status_code, 403
        )
        login = self.client.get("/casework/staff/login/")
        self.assertEqual(
            post(self.client, "/casework/staff/", {"action": "transcripts"}, login).status_code, 403
        )
        page = self.login()
        other = new_case()
        self.assertEqual(
            post(
                self.client,
                "/casework/staff/",
                {"action": "transcript_open", "case_ref": other["public_ref"]},
                page,
            ).status_code,
            403,
        )
        response = self.client.post(
            "/casework/staff/",
            {
                "csrfmiddlewaretoken": hidden(page, "csrfmiddlewaretoken"),
                "action": "transcript_preview",
                "case_ref": self.receipt["public_ref"],
                "synthetic_only": "yes",
                "bundle": SimpleUploadedFile("large.zip", b"x" * (links.MAX_BUNDLE + 1)),
            },
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(TranscriptUpload.objects.count(), 0)
