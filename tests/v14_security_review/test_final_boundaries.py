"""Independent final V14 challenges against real canonical services."""

from dataclasses import replace
from unittest.mock import patch

from apps.arabic_search_eval.models import EvaluationDecision
from apps.pdf_citations import tests as pdf_fixtures
from django.test import TransactionTestCase, override_settings

from apps.arabic_search_eval import review
from apps.arabic_search_eval import test_review as evaluation_fixtures
from apps.casework import services as cases
from apps.timed_citations import tests as timed_fixtures


@override_settings(**evaluation_fixtures.SETTINGS)
class EvaluationReturnBoundary(evaluation_fixtures.ReviewFixture, TransactionTestCase):
    def test_last_authority_callback_cannot_commit_decision_after_identity_revocation(self):
        row = self.propose()
        permits = self.review_authority.permits
        visits, attacks = [], []

        def revoke(**kwargs):
            allowed = permits(**kwargs)
            if kwargs["action"] == "APPROVE":
                visits.append(1)
                if len(visits) == 2:
                    actor = self.directory.identities["publisher"]
                    self.directory.identities["publisher"] = replace(actor, active=False)
                    attacks.append(1)
            return allowed

        denied = False
        with patch.object(self.review_authority, "permits", side_effect=revoke):
            try:
                self.decision(row)
            except cases.CaseConflict:
                denied = True
        self.assertEqual(attacks, [1])
        if not denied:
            print(
                f"EXTERNAL_REVOKED_REVIEWER persisted_decisions={EvaluationDecision.objects.count()}"
            )
        self.assertTrue(denied, "Decision returned after its reviewer identity was revoked")
        self.assertFalse(EvaluationDecision.objects.exists())

    def test_last_view_authority_callback_cannot_disclose_after_identity_revocation(self):
        self.propose()
        permits = self.review_authority.permits
        visits, attacks = [], []

        def revoke(**kwargs):
            allowed = permits(**kwargs)
            if kwargs["action"] == "VIEW":
                visits.append(1)
                if len(visits) == 2:
                    actor = self.directory.identities["editor"]
                    self.directory.identities["editor"] = replace(actor, active=False)
                    attacks.append(1)
            return allowed

        denied = False
        with patch.object(self.review_authority, "permits", side_effect=revoke):
            try:
                review.history(**self.common)
            except cases.CaseConflict:
                denied = True
        self.assertEqual(attacks, [1])
        self.assertTrue(denied, "Evaluation corpus/history escaped after identity revocation")


def assert_final_epoch_expiry_denies(test, operation):
    import inspect
    from datetime import timedelta

    from django.utils import timezone

    from apps.casework import media_boundary

    epoch = media_boundary._epoch
    clock, attacks = [timezone.now()], []

    def slow_atomic_read(policy):
        value = epoch(policy)
        at_exit = any(frame.function == "media_projection_boundary" for frame in inspect.stack())
        if at_exit and len(media_boundary._SCOPES.get()) == 1:
            clock[0] = test.rights.valid_until + timedelta(seconds=1)
            attacks.append(1)
        return value

    denied, result = False, None
    with (
        patch.object(media_boundary, "_epoch", side_effect=slow_atomic_read),
        patch("django.utils.timezone.now", side_effect=lambda: clock[0]),
    ):
        try:
            result = operation()
        except cases.CaseConflict:
            denied = True
    test.assertEqual(attacks, [1], "Only the final outer epoch read advances time")
    if not denied:
        print(f"EXTERNAL_EXPIRED_MEDIA returned_bytes={len(result.get('raw', b''))}")
    test.assertTrue(denied, "Original bytes escaped after deadline crossed in final epoch read")


@override_settings(**pdf_fixtures.SETTINGS)
class PdfFinalEpochExpiry(pdf_fixtures.Fixture, TransactionTestCase):
    def test_pdf_bytes_cannot_outlive_deadline_during_final_epoch_read(self):
        row = self.propose()
        self.confirm(row)
        self.assertEqual(self.opened(row)["raw"], self.pdf["raw"])
        assert_final_epoch_expiry_denies(self, lambda: self.opened(row))


@override_settings(**timed_fixtures.SETTINGS)
class AudioFinalEpochExpiry(timed_fixtures.Fixture, TransactionTestCase):
    def test_audio_bytes_cannot_outlive_deadline_during_final_epoch_read(self):
        row = self.propose()
        self.confirm(row)
        self.assertEqual(self.opened(row)["raw"], self.audio["raw"])
        assert_final_epoch_expiry_denies(self, lambda: self.opened(row))
