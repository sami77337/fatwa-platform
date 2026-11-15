"""The review identity and source remain required after queue staging."""
from dataclasses import replace
from django.test import TransactionTestCase
from apps.delivery_queue.models import DeliveryAttempt
from apps.fast9_case_source_join.answer_drafts import AUTHOR, CASE_KEY
from apps.mufti_review import services
from tests.delivery_queue.author_desk_fixtures import JournalFixture
from tests.mufti_review.provider_fixture import FixtureDirectory


class ReviewedReservationTests(TransactionTestCase):
    def setUp(self):
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()
        self.provider = FixtureDirectory()
        self.options = dict(case_key=CASE_KEY, max_chars=32, split=True, synthetic_fixtures_only=True)
        self.request = services.submit_request(self.fixture.directory, author_id=AUTHOR, **self.options)
        services.record_decision(directory=self.fixture.directory, request_sha256=self.request['request_sha256'],
            subject_id='mufti-fixture', provider=self.provider, action='READY_FOR_SIGNATURE',
            note='', command_id='a' * 32, **self.options)
        from apps.delivery_queue.author_handoff import build_approval_request
        package = build_approval_request(self.fixture.directory, **self.options)
        services.stage_reviewed_response(self.fixture.directory, author_id=AUTHOR,
            response_json=self.fixture.signed_response(package), provider=self.provider,
            verifier=self.fixture.verifier, **self.options)

    def reserve(self, verify_worker=lambda worker, plan: True):
        return services.reserve_reviewed_request(self.fixture.directory,
            request_sha256=self.request['request_sha256'], worker_id='review-worker',
            verify_worker=verify_worker, provider=self.provider,
            verifier=self.fixture.verifier, **self.options)

    def test_current_review_allows_one_scoped_worker_reservation(self):
        lease = self.reserve()
        self.assertIsNotNone(lease)
        self.assertEqual(DeliveryAttempt.objects.count(), 1)

    def test_revoked_review_identity_blocks_reservation_even_with_still_valid_signature(self):
        self.provider.current = replace(self.provider.current, active=False)
        with self.assertRaises(ValueError):
            self.reserve()
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_new_clarification_blocks_already_staged_request(self):
        self.fixture.request_clarification()
        with self.assertRaises(ValueError):
            self.reserve()
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_unauthorized_worker_gets_no_attempt(self):
        with self.assertRaises(ValueError):
            self.reserve(verify_worker=lambda worker, plan: False)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
