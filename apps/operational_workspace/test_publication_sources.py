"""Publication management preserves real precise citations through final callbacks."""

from django.test import TransactionTestCase, override_settings

from apps.casework import services as cases
from apps.experimental_publication import services as editorial
from apps.experimental_publication.models import PublicationAction, PublicationEdition

from . import publication, test_transcript_sources
from .publication_test_support import (
    PUBLICATION_FEATURES,
    PublicationDomainAuthority,
    PublicationFixture,
    PublicationGrants,
    grant_publication,
)


@override_settings(**{**PUBLICATION_FEATURES, "FATWA_PRECISE_CITATIONS_ENABLED": True})
class OperationalPublicationSourceTests(
    test_transcript_sources.CitedTranscriptFixture, TransactionTestCase
):
    immutable_publication_sources = PublicationFixture.immutable_publication_sources
    publication_decide = PublicationFixture.publication_decide

    def setUp(self):
        super().setUp()
        self.authority, self.publication_domain = (
            PublicationGrants(self.receipts),
            PublicationDomainAuthority(),
        )
        configured = override_settings(
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=self.publication_domain,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        row = editorial.create_edition(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            title="نسخة جهزها المفتي لجواب بإحالة دقيقة",
            category="اصطناعي",
            body="النص المحرر يحفظ إحالة الجواب الأصلية.",
            expected_revision=5,
            expected_evidence_version=1,
            synthetic_fixtures_only=True,
        )
        self.edition = PublicationEdition.objects.get(pk=row["id"])
        grant_publication(self.authority, self.publication_domain, self.target, [self.edition])
        self.originals, self.publication_originals = (
            self.state(),
            self.immutable_publication_sources(),
        )

    def decision_values(self, **changes):
        return PublicationFixture.decision_values(self, **{"expected_revision": 5, **changes})

    def test_review_and_independent_publication_keep_current_cross_case_citation(self):
        self.publication_decide()
        result = self.publication_decide(subject="admin", action="APPROVE")
        self.assertEqual(result["editions"][0]["state"], "PUBLISHED")
        self.assertEqual(self.immutable_publication_sources(), self.publication_originals)

    def test_last_operational_callback_source_revocation_rolls_back_review(self):
        called = []
        with self.assertRaises(cases.CaseConflict):
            with publication.decide(**self.common, **self.decision_values()):

                def revoke(values):
                    called.append(values["action"])
                    self.citations.denied.add("READ_SOURCE")

                self.authority.hook = revoke
        self.authority.hook = None
        self.assertTrue(called)
        self.assertEqual(self.state(), self.originals)
        self.assertFalse(PublicationAction.objects.exists())

    def test_last_citation_callback_revokes_current_publication_grant(self):
        called = []
        with self.assertRaises(cases.CaseConflict):
            with publication.decide(**self.common, **self.decision_values()):

                def revoke(values):
                    called.append(values["action"])
                    self.publication_domain.denied.add(("operator", "REVIEW"))

                self.citations.hook = revoke
        self.citations.hook = None
        self.assertTrue(called)
        self.assertEqual(self.state(), self.originals)
