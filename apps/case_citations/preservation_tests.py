"""The internal cross-editor helper preserves exact sources in one transaction."""

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from tests.casework.test_core import TestDirectory

from . import services
from .models import AnswerCitation
from .tests import source_fixture


@override_settings(FATWA_CASE_CITATIONS_ENABLED=True)
class CitationPreservationTests(TransactionTestCase):
    def test_internal_clone_creates_new_ids_preserves_sources_and_rejects_cross_case(self):
        edition = source_fixture()
        receipt = cases.intake_case(
            original_question="حالة اصطناعية",
            source_event_id="clone",
            requester_id="clone",
            idempotency_key="clone",
            synthetic_fixtures_only=True,
        )
        provider = TestDirectory([receipt["public_ref"]])
        common = dict(
            case_id=receipt["case_id"],
            subject_id="synthetic-mufti",
            provider=provider,
            synthetic_fixtures_only=True,
        )
        source = services.read_source(**common, edition_id=edition, source_row_id=2)
        services.save_cited_answer(
            **common,
            text="جواب أول",
            expected_revision=1,
            expected_evidence_version=1,
            selections=[
                dict(
                    edition_id=edition,
                    source_row_id=2,
                    source_sha256=source["source_sha256"],
                    editorial_note="تعليق محفوظ",
                )
            ],
        )
        previous = AnswerRevision.objects.get()
        original = AnswerCitation.objects.get()
        with cases._staff_case(receipt["case_id"], "synthetic-mufti", provider, True) as (
            case,
            actor,
        ):
            case.answer_revision += 1
            answer = AnswerRevision.objects.create(
                case=case,
                revision=case.answer_revision,
                evidence_version=case.evidence_version,
                text="جواب محرر",
                text_sha256=cases._digest("جواب محرر"),
                subject_id=actor.subject_id,
                provider_id=provider.provider_id,
                auth_epoch=actor.auth_epoch,
            )
            case.stage, case.approved_answer = "UNDER_REVIEW", None
            cases._event(case, "SAVE_ANSWER", actor.subject_id, answer=answer)
            services.clone_citations_for_new_answer(previous, answer)
        copied = AnswerCitation.objects.get(answer=answer)
        self.assertNotEqual(copied.pk, original.pk)
        self.assertEqual(copied.source, original.source)
        self.assertEqual(copied.editorial_note, original.editorial_note)
        self.assertEqual(Case.objects.get().answer_revision, 2)
        self.assertIsNone(Case.objects.get().approved_answer_id)
        with self.assertRaises(cases.CaseConflict):
            services.clone_citations_for_new_answer(answer, answer)
        answer.case_id = "00000000-0000-0000-0000-000000000001"
        with self.assertRaises(cases.CaseConflict):
            services.clone_citations_for_new_answer(previous, answer)
