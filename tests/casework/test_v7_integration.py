"""One canonical synthetic case through private evidence, citations and publication."""

from dataclasses import replace

from django.test import TransactionTestCase, override_settings

from apps.case_attachments import services as attachments
from apps.case_attachments.models import CaseAttachment
from apps.case_citations import services as citations
from apps.case_citations.models import AnswerCitation
from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication import services as publications
from apps.experimental_publication.authority import PublicationAuthority
from apps.experimental_publication.models import PublicationEdition
from apps.reference.ingest import ingest_catalog
from apps.requester_access_review.services import requester_snapshot
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_core import TestDirectory
from tests.reference.test_catalog import fixture


class PublisherDirectory(TestDirectory):
    def resolve(self, subject_id):
        if subject_id != "independent-publisher":
            return None
        return replace(super().resolve("synthetic-mufti"), subject_id=subject_id)


class SyntheticPublicationGrant(PublicationAuthority):
    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == "synthetic-case-directory"
            and subject_id == "independent-publisher"
            and auth_epoch == "epoch-1"
            and action in {"APPROVE", "WITHDRAW"}
        )


@override_settings(
    FATWA_CASE_ATTACHMENTS_ENABLED=True,
    FATWA_CASE_CITATIONS_ENABLED=True,
    FATWA_EXPERIMENTAL_PUBLICATION_ENABLED=True,
    FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=SyntheticPublicationGrant(),
)
class V7IntegrationTests(CaseDeliveryFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        spec, rows = fixture()
        spec = replace(spec, source_book_id="622")
        preview = ingest_catalog(spec, rows)
        self.edition_id = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        self.publisher = {
            **self.staff(),
            "subject_id": "independent-publisher",
            "provider": PublisherDirectory([self.a["public_ref"]]),
        }

    def cited_answer(self, text="جواب بشري اصطناعي بإحالة محفوظة"):
        current = cases.read_case(**self.staff())
        source = citations.read_source(**self.staff(), edition_id=self.edition_id, source_row_id=2)
        return citations.save_cited_answer(
            **self.staff(),
            text=text,
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            selections=[
                {
                    "edition_id": self.edition_id,
                    "source_row_id": 2,
                    "source_sha256": source["source_sha256"],
                    "editorial_note": "تعليق بشري مستقل، ليس نص المرجع",
                }
            ],
        )

    def publish(self, title="عنوان تجريبي منقح"):
        current = cases.read_case(**self.staff())
        candidate = publications.create_edition(
            **self.staff(),
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
            title=title,
            category="تصنيف اصطناعي",
            body="نسخة تحريرية خالية من بيانات السائل",
        )
        self.assertEqual(publications.library(**self.publisher_without_case()), [])
        publications.act(**self.staff(), edition_id=candidate["id"], action="REVIEW", reviewed=True)
        publications.act(**self.publisher, edition_id=candidate["id"], action="APPROVE")
        return candidate

    def publisher_without_case(self):
        return {key: value for key, value in self.publisher.items() if key != "case_id"}

    def test_same_case_attachment_clarification_citation_signed_private_answer_and_publication(
        self,
    ):
        raw = "تفصيل اصطناعي محفوظ حرفيًا\n".encode()
        upload = attachments.upload(
            token=self.a["token"],
            raw=raw,
            filename="fixture.txt",
            media_type="text/plain",
            expected_revision=1,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(
            attachments.staff_read(**self.staff(), attachment_id=upload["id"])["raw"], raw
        )
        foreign = self.intake("foreign")
        with self.assertRaises(cases.CaseConflict):
            attachments.requester_read(
                token=foreign["token"], attachment_id=upload["id"], synthetic_fixtures_only=True
            )
        current = cases.read_case(**self.staff())
        clarification = cases.request_clarification(
            **self.staff(),
            text="وضح التفصيل الاصطناعي",
            expected_revision=current["revision"],
            expected_evidence_version=current["evidence_version"],
        )
        cases.add_followup(
            token=self.a["token"],
            text="رد السائل الاصطناعي",
            expected_revision=clarification["revision"],
            synthetic_fixtures_only=True,
        )
        draft = self.cited_answer()
        approved = cases.record_decision(
            **self.staff(),
            answer_id=draft["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=draft["revision"],
            expected_evidence_version=draft["evidence_version"],
        )
        snapshot = requester_snapshot(
            self.a["token"],
            show_approved_answer=True,
            verifier=self.channel_verifier,
            synthetic_fixtures_only=True,
        )
        self.assertIsNone(snapshot["private_answer"])
        self.stage()
        self.deliver()  # Test-generated signed receipts only; no network sender.
        snapshot = requester_snapshot(
            self.a["token"],
            show_approved_answer=True,
            verifier=self.channel_verifier,
            synthetic_fixtures_only=True,
        )
        self.assertEqual(snapshot["private_answer"]["text"], draft["answers"][-1]["text"])
        self.assertFalse(snapshot["case"]["read_confirmed"])
        candidate = self.publish()
        library = publications.library(**self.publisher_without_case(), query="عنوان")
        self.assertEqual([row["id"] for row in library], [candidate["id"]])
        self.assertEqual(len(library[0]["citations"]), 1)
        self.assertNotIn("case_id", library[0])
        case = Case.objects.get(pk=self.a["case_id"])
        self.assertEqual(case.approved_answer_id, case.answers.get().pk)
        self.assertEqual(case.revision, approved["revision"])
        self.assertEqual(CaseAttachment.objects.get().evidence.case_id, case.pk)
        self.assertEqual(AnswerCitation.objects.get().answer_id, case.approved_answer_id)
        self.assertEqual(PublicationEdition.objects.get().answer_id, case.approved_answer_id)
        publications.act(**self.publisher, edition_id=candidate["id"], action="WITHDRAW")
        self.assertEqual(publications.library(**self.publisher_without_case()), [])

    def test_new_facts_and_citation_revision_close_prior_private_and_public_exposure(self):
        draft = self.cited_answer()
        cases.record_decision(
            **self.staff(),
            answer_id=draft["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=draft["revision"],
            expected_evidence_version=draft["evidence_version"],
        )
        self.stage()
        self.deliver()
        candidate = self.publish()
        current = cases.read_case(**self.staff())
        attachments.upload(
            token=self.a["token"],
            raw=b"new synthetic facts",
            filename="new.txt",
            media_type="text/plain",
            expected_revision=current["revision"],
            synthetic_fixtures_only=True,
        )
        self.assertEqual(publications.library(**self.publisher_without_case()), [])
        snapshot = requester_snapshot(
            self.a["token"],
            show_approved_answer=True,
            verifier=self.channel_verifier,
            synthetic_fixtures_only=True,
        )
        self.assertIsNone(snapshot["private_answer"])
        draft = self.cited_answer("نسخة جديدة مرتبطة بالوقائع الجديدة")
        self.assertIsNone(draft["approved_answer_id"])
        self.assertEqual(AnswerCitation.objects.count(), 2)
        self.assertEqual(PublicationEdition.objects.get(pk=candidate["id"]).number, 1)
        with self.assertRaises(cases.CaseConflict):
            self.stage()
