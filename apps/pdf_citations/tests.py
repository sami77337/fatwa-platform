"""Synthetic real-PDF contracts over PostgreSQL and the canonical private assets."""

import io
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.core import signing
from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from pypdf import PdfWriter

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.case_attachments import services as attachments
from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.experimental_publication.tests import Directory
from apps.timed_citations.tests import ExactMediaRights
from tests.casework.test_http import WEB_SETTINGS, post

from . import services
from .models import PdfCitation, PdfCitationAction
from .views import SALT

SETTINGS = {
    **WEB_SETTINGS,
    "ROOT_URLCONF": "apps.pdf_citations.urls",
    "MIDDLEWARE": [
        "apps.platform_recovery.middleware.MaintenanceGuard",
        "apps.pdf_citations.guard.PdfCitationGuard",
        "django.middleware.csrf.CsrfViewMiddleware",
    ],
    "FATWA_PDF_CITATIONS_ENABLED": True,
    "FATWA_ANSWER_MEDIA_ENABLED": True,
    "FATWA_CASE_ATTACHMENTS_ENABLED": True,
    "FATWA_SOURCE_RIGHTS_ENFORCED": True,
}


def pdf_fixture(pages=3):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=400)
    buffer = io.BytesIO()
    writer.write(buffer)
    return dict(
        raw=buffer.getvalue(), filename="private-synthetic.pdf", media_type="application/pdf"
    )


class Fixture:
    def setUp(self):
        super().setUp()
        self.receipt = cases.intake_case(
            original_question="PRIVATE synthetic question",
            source_event_id="pdf-fixture",
            requester_id="synthetic-one",
            idempotency_key="pdf-fixture",
            synthetic_fixtures_only=True,
        )
        self.directory = Directory([self.receipt["public_ref"]])
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.pdf = pdf_fixture()
        self.attachment = attachments.upload(
            token=self.receipt["token"],
            **self.pdf,
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        self.save()
        self.part = AnswerPart.objects.get(kind="FILE")
        self.rights = ExactMediaRights(self.receipt["public_ref"])
        self.rights.pins = {
            ("ATTACHMENT", self.attachment["id"], self.attachment["sha256"]),
            ("ANSWER_MEDIA", str(self.part.pk), self.part.sha256),
        }
        overlay = override_settings(
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
        )
        overlay.enable()
        self.addCleanup(overlay.disable)
        self.pin = services.inspect_source(
            **self.common, kind="ATTACHMENT", source_id=self.attachment["id"]
        )

    def save(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        return media.save_multipart_answer(
            **self.common,
            text="PRIVATE human answer",
            files=[self.pdf],
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )

    def propose(self, **kw):
        case = Case.objects.get(pk=self.receipt["case_id"])
        args = dict(
            self.common,
            source_pin=self.pin,
            page_number=2,
            reason="PRIVATE human locator",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        return services.propose(**{**args, **kw})

    def confirm(self, row):
        return services.act(**self.common, citation_id=row["id"], action="CONFIRM", confirmed=True)

    def opened(self, row, **kw):
        return services.open_pdf(**self.common, citation_id=row["id"], **kw)

    def approval_guard(self):
        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            return services.for_locked_answer(
                answer=case.answers.get(revision=case.answer_revision),
                actor=actor,
                provider=self.directory,
            )


@override_settings(**SETTINGS)
class PdfTests(Fixture, TransactionTestCase):
    def test_actual_page_count_and_explicit_human_mapping_preserve_original(self):
        self.assertEqual(self.pin["page_count"], 3)
        row = self.propose(printed_label="تمهيد ب", printed_confirmed=True)
        with self.assertRaises(cases.CaseConflict):
            self.opened(row)
        self.assertEqual(self.opened(row, review=True)["raw"], self.pdf["raw"])
        with self.assertRaises(cases.CaseConflict):
            self.approval_guard()
        self.confirm(row)
        opened = self.opened(row)
        self.assertEqual(opened["raw"], self.pdf["raw"])
        self.assertEqual((opened["page_number"], opened["printed_label"]), (2, "تمهيد ب"))
        self.assertEqual(self.approval_guard()[0]["source"], self.pin)
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(
            Case.objects.get(pk=self.receipt["case_id"]).source.original_question,
            "PRIVATE synthetic question",
        )

    def test_invalid_pages_forged_count_version_digest_and_guessed_mapping_deny(self):
        for page in (0, -1, 4, True, 1.5, "2", float("nan")):
            with self.subTest(page=page), self.assertRaises(cases.CaseConflict):
                self.propose(page_number=page)
        for key, value in (
            ("page_count", 10),
            ("version", 999),
            ("version", True),
            ("sha256", "0" * 64),
            ("metadata_sha256", "f" * 64),
        ):
            with self.subTest(key=key), self.assertRaises(cases.CaseConflict):
                self.propose(source_pin={**self.pin, key: value})
        for label, confirmation in (
            ("7", False),
            ("", True),
            (" 7", True),
            ("7\n", True),
            ("7", 1),
            ("x" * 41, True),
        ):
            with self.subTest(label=label), self.assertRaises(cases.CaseConflict):
                self.propose(printed_label=label, printed_confirmed=confirmation)
        self.assertEqual(PdfCitation.objects.count(), 0)
        row = self.propose()
        self.assertEqual(self.opened(row, review=True)["printed_label"], "")

    def test_correction_append_only_and_exact_old_version_never_redirects(self):
        old_pin = services.inspect_source(
            **self.common, kind="ANSWER_MEDIA", source_id=str(self.part.pk)
        )
        first = self.propose(source_pin=old_pin)
        self.confirm(first)
        self.pdf = pdf_fixture(2)
        self.save()
        with self.assertRaises(cases.CaseConflict):
            self.opened(first)
        history = services.desk(**self.common)["history"][0]
        self.assertFalse(history["current"])
        self.assertEqual(history["source"], old_pin)
        second = self.propose(
            source_pin=old_pin,
            replaces_id=first["id"],
            page_number=3,
            reason="Explicit human selection of old original",
        )
        self.confirm(second)
        self.assertEqual(self.opened(second)["page_count"], 3)
        self.assertEqual(PdfCitation.objects.get(pk=second["id"]).part_id, self.part.pk)
        self.assertEqual(len(self.approval_guard()), 1)
        from .integration import require_for_answer

        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            with self.assertRaises(cases.CaseConflict):
                require_for_answer(
                    case.answers.get(revision=1), actor=actor, provider=self.directory
                )
        for operation in (
            lambda: PdfCitation.objects.all().update(page_number=1),
            lambda: PdfCitation.objects.all().delete(),
            lambda: PdfCitationAction.objects.all().delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_read_cite_expiry_and_withdrawal_redact_source_label_and_reason(self):
        row = self.propose(printed_label="PRIVATE label", printed_confirmed=True)
        self.confirm(row)
        for action in ("READ_MEDIA", "CITE"):
            self.rights.actions.remove(action)
            for operation in (lambda: self.opened(row), self.approval_guard):
                with self.assertRaises(cases.CaseConflict):
                    operation()
            projection = services.desk(**self.common)
            self.assertEqual(projection["sources"], [])
            self.assertNotIn("PRIVATE", str(projection))
            self.assertNotIn(self.pin["filename"], str(projection))
            self.rights.actions.add(action)
        with patch.object(timezone, "now", return_value=timezone.now() + timedelta(minutes=2)):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)
        self.rights.actions.clear()
        services.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        self.rights.actions.update({"READ_MEDIA", "CITE"})
        with self.assertRaises(cases.CaseConflict):
            self.approval_guard()
        with self.assertRaises(cases.CaseConflict):
            self.confirm(row)
        self.assertEqual(PdfCitation.objects.count(), 1)
        self.assertEqual(AnswerRevision.objects.count(), 1)

    def test_scope_and_identity_change_during_read_deny(self):
        row = self.propose()
        self.confirm(row)
        original = services.validate

        def changed(*args):
            result = original(*args)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="changed"
            )
            return result

        with patch.object(services, "validate", side_effect=changed):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)
        self.directory.identities["editor"] = replace(
            self.directory.identities["editor"], auth_epoch="epoch-1", case_keys=frozenset()
        )
        with self.assertRaises(cases.CaseConflict):
            self.opened(row)
        with self.assertRaises(cases.CaseConflict):
            services.desk(**self.common)

    def test_missing_parser_proof_and_disabled_or_non_explicit_rights_deny(self):
        with patch.object(services, "validate", side_effect=services.MediaValidationError("bad")):
            with self.assertRaises(cases.CaseConflict):
                self.propose()
        for config in (
            {"FATWA_PDF_CITATIONS_ENABLED": False},
            {"FATWA_RESEARCH_WORKSPACE_RIGHTS": None},
            {"FATWA_SOURCE_RIGHTS_ENFORCED": "false"},
        ):
            with override_settings(**config), self.assertRaises(cases.CaseConflict):
                self.propose()
        text_part = AnswerPart.objects.get(kind="TEXT")
        with self.assertRaises(cases.CaseConflict):
            services.inspect_source(**self.common, kind="ANSWER_MEDIA", source_id=str(text_part.pk))

    def test_expiry_during_projection_rolls_back_and_final_rights_rechecked(self):
        instant = timezone.now()
        clock = [instant]
        original = services._identity

        def expire(case, actor, provider):
            original(case, actor, provider)
            clock[0] = instant + timedelta(minutes=2)

        with (
            patch.object(timezone, "now", side_effect=lambda: clock[0]),
            patch.object(services, "_identity", side_effect=expire),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.propose()
        self.assertEqual(PdfCitation.objects.count(), 0)
        # A CITE deadline callback may revoke READ; no earlier permission result is trusted.
        original_deadline = self.rights.grant_deadline

        def revoke(**kw):
            deadline = original_deadline(**kw)
            if kw["action"] == "CITE":
                self.rights.actions.discard("READ_MEDIA")
            return deadline

        with patch.object(self.rights, "grant_deadline", side_effect=revoke):
            with self.assertRaises(cases.CaseConflict):
                self.propose()
        self.assertEqual(PdfCitation.objects.count(), 0)

    def test_database_rejects_invalid_page_count_owner_and_non_human_label(self):
        row = PdfCitation.objects.get(pk=self.propose()["id"])
        values = {
            f.name: getattr(row, f.name)
            for f in PdfCitation._meta.fields
            if f.name not in {"id", "series", "number", "previous", "created_at"}
        }
        for changes in (
            {"page_number": 4},
            {"printed_label": "6", "printed_confirmed": False},
            {"snapshot": {**row.snapshot, "sha256": "0" * 64}},
            {"snapshot": {**row.snapshot, "page_count": 4}, "page_count": 4},
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                PdfCitation.objects.create(**{**values, **changes}, number=1)
        other = cases.intake_case(
            original_question="other",
            source_event_id="db-other",
            requester_id="other",
            idempotency_key="db-other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PdfCitation.objects.create(
                **{**values, "case": Case.objects.get(pk=other["case_id"])}, number=1
            )

    def test_withdrawal_after_approval_and_no_retroactive_annotation(self):
        row = self.propose()
        self.confirm(row)
        self.approval_guard()  # Explicit hook: shared automatic wiring belongs to integration.
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.record_decision(
            **self.common,
            answer_id=case.answers.get().pk,
            action="APPROVE",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        with self.assertRaises(cases.CaseConflict):
            self.propose()
        with self.assertRaises(cases.CaseConflict):
            self.opened(row, review=True)
        services.act(**self.common, citation_id=row["id"], action="WITHDRAW", confirmed=True)
        with self.assertRaises(cases.CaseConflict):
            self.approval_guard()
        self.assertIsNotNone(Case.objects.get(pk=self.receipt["case_id"]).approved_answer_id)

    def test_correction_notes_redacted_when_previous_source_right_revoked(self):
        first = self.propose()
        pin = services.inspect_source(
            **self.common, kind="ANSWER_MEDIA", source_id=str(self.part.pk)
        )
        second = self.propose(
            source_pin=pin, replaces_id=first["id"], reason="PRIVATE previous document"
        )
        self.confirm(second)
        self.rights.pins.remove(("ATTACHMENT", self.attachment["id"], self.attachment["sha256"]))
        history = services.desk(**self.common)["history"]
        self.assertNotIn("PRIVATE previous document", str(history))
        self.assertEqual(next(r for r in history if r["id"] == second["id"])["reason"], "")

    def test_native_forms_csrf_signed_pin_sandbox_and_private_bytes(self):
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        desk = {"action": "pdf_desk", "case_ref": self.receipt["public_ref"]}
        self.assertEqual(client.post("/casework/staff/", desk).status_code, 403)
        page = client.get("/casework/staff/login/")
        post(
            client,
            "/casework/staff/login/",
            {"credential": "synthetic-editor-credential-32-characters"},
            page,
        )
        page = post(client, "/casework/staff/", desk, client.get("/casework/staff/"))
        self.assertContains(page, "3 صفحة")
        fields = dict(
            action="pdf_propose",
            case_ref=self.receipt["public_ref"],
            source_pin=signing.dumps(self.pin, salt=SALT),
            page_number="2",
            printed_label="",
            printed_confirmed="no",
            reason="Human page",
            replaces_id="",
            revision="3",
            evidence_version="2",
        )
        invalid = post(client, "/casework/staff/", {**fields, "source_pin": "forged"}, page)
        self.assertEqual(invalid.status_code, 400)
        page = post(client, "/casework/staff/", fields, page)
        self.assertEqual(page.status_code, 200, page.content)
        row = PdfCitation.objects.get()
        page = post(
            client,
            "/casework/staff/",
            dict(
                action="pdf_preview", case_ref=self.receipt["public_ref"], citation_id=str(row.pk)
            ),
            page,
        )
        self.assertContains(page, "review-document/#page=2")
        review_url = f"/casework/staff/pdf-citations/{row.pk}/review-document/"
        response = client.get(review_url)
        self.assertEqual(response.content, self.pdf["raw"])
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertIn("no-store", response["Cache-Control"])
        url = f"/casework/staff/pdf-citations/{row.pk}/document/"
        self.assertEqual(client.get(url).status_code, 404)
        self.confirm({"id": str(row.pk)})
        self.assertEqual(client.get(url).content, self.pdf["raw"])
        self.assertEqual(client.head(url).content, b"")
        self.assertEqual(client.head(url)["Content-Length"], str(len(self.pdf["raw"])))
        self.assertEqual(client.get(url + "?page=2").status_code, 405)
        self.assertEqual(client.get(url, REMOTE_ADDR="192.0.2.1").status_code, 403)
        self.assertEqual(client.get(url, HTTP_X_FORWARDED_FOR="127.0.0.1").status_code, 403)
        self.assertEqual(
            Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1").get(url).status_code, 404
        )
        self.rights.actions.clear()
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.head(url).status_code, 404)

    def test_concurrent_correction_has_one_successor(self):
        from concurrent.futures import ThreadPoolExecutor

        from django.db import connections

        first = self.propose()

        def correct(_):
            try:
                return self.propose(replaces_id=first["id"])["state"]
            except cases.CaseConflict:
                return "CONFLICT"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(correct, range(2))), ["PROPOSED", "CONFLICT"])
        self.assertEqual(PdfCitation.objects.count(), 2)

    def test_expiry_at_final_byte_boundary_denies_response(self):
        row = self.propose()
        self.confirm(row)
        instant = timezone.now()
        clock = [instant]
        original = services._rights
        calls = [0]

        def expire(*args):
            original(*args)
            calls[0] += 1
            if calls[0] == 3:
                clock[0] = instant + timedelta(minutes=2)

        with (
            patch.object(timezone, "now", side_effect=lambda: clock[0]),
            patch.object(services, "_rights", side_effect=expire),
        ):
            with self.assertRaises(cases.CaseConflict):
                self.opened(row)

    def test_integration_guard_keeps_persisted_annotations_when_ui_or_schema_disabled(self):
        from django.conf import settings

        from .integration import require_for_answer

        row = self.propose()
        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            answer = case.answers.get()
            with self.assertRaises(cases.CaseConflict):
                require_for_answer(answer, actor=actor, provider=self.directory)
        self.confirm(row)
        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            answer = case.answers.get()
            self.assertEqual(
                require_for_answer(answer, actor=actor, provider=self.directory),
                self.rights.valid_until,
            )
            with (
                override_settings(FATWA_PDF_CITATIONS_ENABLED=False),
                self.assertRaises(cases.CaseConflict),
            ):
                require_for_answer(answer, actor=actor, provider=self.directory)
            installed = [name for name in settings.INSTALLED_APPS if name != "apps.pdf_citations"]
            with override_settings(INSTALLED_APPS=installed), self.assertRaises(cases.CaseConflict):
                require_for_answer(answer, actor=actor, provider=self.directory)
            with self.assertRaises(cases.CaseConflict):
                require_for_answer(answer)  # No recorded approval yet.
        case = Case.objects.get(pk=self.receipt["case_id"])
        cases.record_decision(
            **self.common,
            answer_id=case.answers.get().pk,
            action="APPROVE",
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        )
        with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
            case,
            actor,
        ):
            answer = case.answers.get()
            self.assertEqual(require_for_answer(answer), self.rights.valid_until)
            self.directory.identities["editor"] = replace(
                self.directory.identities["editor"], auth_epoch="new"
            )
            with self.assertRaises(cases.CaseConflict):
                require_for_answer(answer)

    def test_each_exact_action_expiry_is_required_and_earliest_is_returned(self):
        from .integration import require_for_answer

        row = self.propose()
        self.confirm(row)
        for action in ("READ_MEDIA", "CITE"):

            def deadline(**kw):
                return (
                    timezone.now() - timedelta(seconds=1)
                    if kw["action"] == action
                    else self.rights.valid_until
                )

            with patch.object(self.rights, "grant_deadline", side_effect=deadline):
                with self.assertRaises(cases.CaseConflict):
                    self.opened(row)
                with self.assertRaises(cases.CaseConflict):
                    self.approval_guard()
        earliest = timezone.now() + timedelta(seconds=10)
        with patch.object(
            self.rights,
            "grant_deadline",
            side_effect=lambda **kw: (
                earliest if kw["action"] == "READ_MEDIA" else self.rights.valid_until
            ),
        ):
            with cases._staff_case(self.common["case_id"], "editor", self.directory, True) as (
                case,
                actor,
            ):
                self.assertEqual(
                    require_for_answer(case.answers.get(), actor=actor, provider=self.directory),
                    earliest,
                )


class MigrationTests(TransactionTestCase):
    def test_integrity_migration_rolls_back_and_reapplies(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        try:
            executor.migrate([("pdf_citations", "0001_initial")])
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regprocedure('pdf_citations_guard()')")
                self.assertIsNone(cursor.fetchone()[0])
        finally:
            MigrationExecutor(connection).migrate([("pdf_citations", "0002_integrity")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN ('pdf_citations_guard','pdf_citations_action_guard')"
            )
            self.assertEqual(cursor.fetchone()[0], 2)
