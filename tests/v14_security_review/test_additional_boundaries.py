"""Independent local rescue checks; no production data or product monkeypatches."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from apps.arabic_search_eval.models import EvaluationDecision, EvaluationRevision
from apps.pdf_citations.models import PdfCitation
from apps.timed_citations.models import TimedCitation
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.arabic_search_eval import review
from apps.arabic_search_eval import test_review as evaluation_fixtures
from apps.casework import services as cases
from apps.pdf_citations import services as pdf
from apps.pdf_citations import tests as pdf_fixtures
from apps.timed_citations import services as audio
from apps.timed_citations import tests as audio_fixtures
from tests.v14_security_review.test_final_boundaries import assert_final_epoch_expiry_denies


@override_settings(**evaluation_fixtures.SETTINGS)
class EvaluationAdditional(evaluation_fixtures.ReviewFixture, TransactionTestCase):
    def _during_last_permit(self, action, subject, mutation, operation):
        original = self.review_authority.permits
        visits, attacks = [], []

        def late(**kwargs):
            result = original(**kwargs)
            if kwargs["action"] == action:
                visits.append(1)
                if len(visits) == 2:
                    self.directory.identities[subject] = mutation(
                        self.directory.identities[subject]
                    )
                    attacks.append(1)
            return result

        with patch.object(self.review_authority, "permits", side_effect=late):
            with self.assertRaises(cases.CaseConflict):
                operation()
        self.assertEqual(attacks, [1])

    def test_proposal_revoked_author_rolls_back_revision(self):
        self._during_last_permit(
            "PROPOSE", "editor", lambda x: replace(x, active=False), self.propose
        )
        self.assertFalse(EvaluationRevision.objects.exists())

    def test_rejection_epoch_change_rolls_back_decision(self):
        row = self.propose()
        self._during_last_permit(
            "REJECT",
            "publisher",
            lambda x: replace(x, auth_epoch="epoch-revoked"),
            lambda: self.decision(row, action="REJECT"),
        )
        self.assertFalse(EvaluationDecision.objects.exists())

    def test_history_scope_loss_denies_projection(self):
        self.propose()
        self._during_last_permit(
            "VIEW",
            "editor",
            lambda x: replace(x, case_keys=frozenset()),
            lambda: review.history(**self.common),
        )

    def test_proposal_expired_author_rolls_back_revision(self):
        self._during_last_permit(
            "PROPOSE",
            "editor",
            lambda x: replace(x, valid_until=timezone.now() - timedelta(seconds=1)),
            self.propose,
        )
        self.assertFalse(EvaluationRevision.objects.exists())


@override_settings(**pdf_fixtures.SETTINGS)
class PdfMetadataAdditional(pdf_fixtures.Fixture, TransactionTestCase):
    def test_propose_expiry_rolls_back_locator(self):
        assert_final_epoch_expiry_denies(self, self.propose)
        self.assertFalse(PdfCitation.objects.exists())

    def test_inspect_metadata_does_not_outlive_final_epoch(self):
        assert_final_epoch_expiry_denies(
            self,
            lambda: pdf.inspect_source(
                **self.common, kind="ATTACHMENT", source_id=self.attachment["id"]
            ),
        )

    def test_review_pdf_does_not_outlive_final_epoch(self):
        row = self.propose()
        assert_final_epoch_expiry_denies(self, lambda: self.opened(row, review=True))


@override_settings(**audio_fixtures.SETTINGS)
class AudioMetadataAdditional(audio_fixtures.Fixture, TransactionTestCase):
    def test_propose_expiry_rolls_back_locator(self):
        assert_final_epoch_expiry_denies(self, self.propose)
        self.assertFalse(TimedCitation.objects.exists())

    def test_inspect_metadata_does_not_outlive_final_epoch(self):
        assert_final_epoch_expiry_denies(
            self,
            lambda: audio.inspect_source(
                **self.common, kind="ATTACHMENT", source_id=self.attachment["id"]
            ),
        )

    def test_review_audio_does_not_outlive_final_epoch(self):
        row = self.propose()
        assert_final_epoch_expiry_denies(self, lambda: self.opened(row, review=True))
