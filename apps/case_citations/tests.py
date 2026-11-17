"""Focused PostgreSQL services and authenticated forms for exact source citations."""

from dataclasses import replace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.reference.ingest import ingest_catalog
from tests.casework.test_core import TestDirectory
from tests.casework.test_http import Directory, post
from tests.reference.test_catalog import fixture

from . import services
from .models import AnswerCitation


def source_fixture():
    spec, rows = fixture()
    spec = replace(spec, source_book_id="622")
    preview = ingest_catalog(spec, rows)
    return ingest_catalog(spec, rows, dry_run=False, expected_checksum=preview.checksum).edition_id


@override_settings(FATWA_CASE_CITATIONS_ENABLED=True)
class CitationTests(TransactionTestCase):
    def setUp(self):
        self.edition = source_fixture()
        self.receipt = cases.intake_case(
            original_question="سؤال اصطناعي للبحث",
            source_event_id="citation-source",
            requester_id="citation-requester",
            idempotency_key="citation-intake",
            synthetic_fixtures_only=True,
        )
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="synthetic-mufti",
            provider=TestDirectory([self.receipt["public_ref"]]),
            synthetic_fixtures_only=True,
        )

    def selection(self, row=2):
        found = services.read_source(**self.common, edition_id=self.edition, source_row_id=row)
        return dict(
            edition_id=self.edition,
            source_row_id=row,
            source_sha256=found["source_sha256"],
            editorial_note="تعليق بشري مستقل",
        )

    def save(self, revision=1, **extra):
        return services.save_cited_answer(
            **self.common,
            text="جواب بشري اصطناعي",
            selections=extra.pop("selections", [self.selection()]),
            expected_revision=revision,
            expected_evidence_version=1,
            **extra,
        )

    def test_search_exact_edition_snapshot_original_and_note_are_distinct(self):
        found = services.search_sources(**self.common, query="فرع", edition_id=self.edition)
        self.assertEqual(len(found["results"]), 2)
        draft = self.save()
        self.assertEqual(draft["revision"], 2)
        citation = services.read_citations(**self.common)[0]
        self.assertEqual(citation["answer_id"], draft["answers"][0]["id"])
        self.assertEqual(citation["source"]["heading_title"], "فَرْعٌ تَجْرِيبِيّ")
        self.assertEqual(citation["source"]["printed_page"], 2)
        self.assertEqual(citation["source"]["source_input_sha256"], "b" * 64)
        self.assertEqual(citation["editorial_note"], "تعليق بشري مستقل")
        self.assertEqual(AnswerRevision.objects.count(), 1)
        self.assertEqual(
            cases.requester_status(self.receipt["token"], synthetic_fixtures_only=True)[
                "delivery_verified"
            ],
            False,
        )

    def test_citation_change_creates_new_revision_and_invalidates_approval(self):
        draft = self.save()
        cases.record_decision(
            **self.common,
            answer_id=draft["answers"][0]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        current = self.save(3, selections=[self.selection(3)])
        self.assertIsNone(current["approved_answer_id"])
        self.assertEqual(current["status"], "UNDER_REVIEW")
        self.assertEqual(AnswerRevision.objects.count(), 2)
        self.assertEqual(AnswerCitation.objects.count(), 2)
        old = services.read_citations(**self.common, answer_id=draft["answers"][0]["id"])
        self.assertEqual(old[0]["source"]["source_row_id"], 2)

    def test_fabricated_source_stale_pin_duplicate_and_unknown_fields_do_not_write(self):
        valid = self.selection()
        for selection in [
            dict(valid, source_row_id=999),
            dict(valid, source_sha256="0" * 64),
            dict(valid, invented_quote="not sourced"),
        ]:
            with self.assertRaises(cases.CaseConflict):
                self.save(selections=[selection])
        with self.assertRaises(cases.CaseConflict):
            self.save(selections=[valid, valid])
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(Case.objects.get().revision, 1)

    def test_stale_forms_clarification_and_new_facts_block_old_citation_form(self):
        cases.request_clarification(
            **self.common, text="استيضاح بشري", expected_revision=1, expected_evidence_version=1
        )
        with self.assertRaises(cases.CaseConflict):
            self.save(2)
        cases.add_followup(
            token=self.receipt["token"],
            text="وقائع إضافية",
            expected_revision=2,
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            self.save(3)
        self.assertEqual(AnswerRevision.objects.count(), 0)

    def test_wrong_scope_role_and_default_disabled_reject_sources_and_saves(self):
        for provider in [
            TestDirectory([]),
            TestDirectory([self.receipt["public_ref"]], role="ORGANIZER_ADMIN"),
        ]:
            with self.assertRaises(cases.CaseConflict):
                services.search_sources(**dict(self.common, provider=provider), query="فرع")
        with override_settings(FATWA_CASE_CITATIONS_ENABLED=False):
            with self.assertRaises(cases.CaseConflict):
                services.search_sources(**self.common)
        other = cases.intake_case(
            original_question="قضية ثانية",
            source_event_id="other-source",
            requester_id="other",
            idempotency_key="other",
            synthetic_fixtures_only=True,
        )
        with self.assertRaises(cases.CaseConflict):
            services.search_sources(**dict(self.common, case_id=other["case_id"]))

    def test_atomic_rollback_and_database_immutability_and_late_append_rejection(self):
        with patch.object(AnswerCitation.objects, "create", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(AnswerRevision.objects.count(), 0)
        self.assertEqual(Case.objects.get().revision, 1)
        draft = self.save()
        row = AnswerCitation.objects.get()
        for mutate in [
            lambda: AnswerCitation.objects.filter(pk=row.pk).update(editorial_note="x"),
            lambda: AnswerCitation.objects.filter(pk=row.pk).delete(),
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                mutate()
        another = services.read_source(**self.common, edition_id=self.edition, source_row_id=3)
        from apps.reference.models import ReferenceHeading

        # Even an undecided answer cannot acquire citations in a later transaction.
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerCitation.objects.create(
                answer_id=row.answer_id,
                heading=ReferenceHeading.objects.get(edition_id=self.edition, source_row_id=3),
                ordinal=2,
                editorial_note="",
                **another,
            )
        cases.record_decision(
            **self.common,
            answer_id=draft["answers"][0]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AnswerCitation.objects.create(
                answer_id=row.answer_id,
                heading=ReferenceHeading.objects.get(edition_id=self.edition, source_row_id=3),
                ordinal=2,
                editorial_note="",
                **another,
            )

    def test_authenticated_native_search_selection_save_and_csrf(self):
        directory = Directory()
        directory.grant(self.receipt["public_ref"])
        client = Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        with override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
            FATWA_CASEWORK_WEB_ENABLED=True,
            ROOT_URLCONF="config.campaign_urls",
        ):
            page = client.get("/casework/staff/login/")
            logged = post(
                client, "/casework/staff/login/", {"credential": directory.credential}, page
            )
            self.assertEqual(logged.status_code, 303)
            page = client.get("/casework/staff/")
            page = post(
                client,
                "/casework/staff/",
                dict(
                    action="citation_search",
                    case_ref=self.receipt["public_ref"],
                    edition_id=self.edition,
                    query="فرع",
                ),
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            self.assertContains(page, "اختيار هذا الموضع")
            page = post(
                client,
                "/casework/staff/",
                dict(
                    action="citation_select",
                    case_ref=self.receipt["public_ref"],
                    edition_id=self.edition,
                    source_row_id=2,
                ),
                page,
            )
            self.assertEqual(page.status_code, 200, page.content)
            from tests.casework.test_http import hidden

            fields = dict(
                action="citation_save",
                case_ref=self.receipt["public_ref"],
                edition_id=self.edition,
                source_row_id=2,
                source_sha256=hidden(page, "source_sha256"),
                editorial_note="<b>تحرير</b>",
                text="جواب اصطناعي",
                revision=1,
                evidence_version=1,
                confirm="yes",
            )
            self.assertEqual(client.post("/casework/staff/", fields).status_code, 403)
            saved = post(client, "/casework/staff/", fields, page)
            self.assertEqual(saved.status_code, 200, saved.content)
            self.assertContains(saved, "&lt;b&gt;تحرير&lt;/b&gt;")
            self.assertIn("no-store", saved["Cache-Control"])
            self.assertEqual(AnswerCitation.objects.count(), 1)
