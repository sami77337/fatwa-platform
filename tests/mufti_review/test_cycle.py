"""Real journal + PostgreSQL tests for human review separate from signing."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import importlib
import importlib.util
import os
from threading import Barrier
from unittest.mock import patch

from django.db import connections, close_old_connections, connection, IntegrityError
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from apps.delivery_queue.models import ApprovalClaim, DeliveryAttempt
from apps.fast9_case_source_join.answer_drafts import AUTHOR, CASE_KEY
from tests.delivery_queue.author_desk_fixtures import JournalFixture, BODY


class MuftiReviewCycleTests(TransactionTestCase):
    def setUp(self):
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.mufti_review.services'), 'review service must be implemented')
        return importlib.import_module('apps.mufti_review.services')

    def provider(self):
        identity = importlib.import_module('apps.mufti_review.identity')
        class Provider(identity.MuftiIdentityProvider):
            provider_id = 'test-directory'
            def __init__(self):
                self.current = identity.MuftiIdentity('mufti-fixture', 'MUFTI', True,
                    frozenset({CASE_KEY}), 'epoch-1', timezone.now() + timedelta(minutes=10))
                self.unavailable = False
            def authenticate(self, credential):
                if credential != 'M' * 64:
                    raise ValueError('unauthenticated')
                return self.resolve('mufti-fixture')
            def resolve(self, subject_id):
                if self.unavailable:
                    raise OSError('identity unavailable')
                return self.current if subject_id == self.current.subject_id else None
        return Provider()

    def package(self):
        from apps.delivery_queue.author_handoff import build_approval_request
        return build_approval_request(self.fixture.directory, case_key=CASE_KEY,
            max_chars=32, split=True, synthetic_fixtures_only=True)

    def submit(self):
        return self.api().submit_request(self.fixture.directory, case_key=CASE_KEY,
            max_chars=32, split=True, author_id=AUTHOR, synthetic_fixtures_only=True)

    def decide(self, provider, action='READY_FOR_SIGNATURE', note='', **changes):
        values = dict(directory=self.fixture.directory, case_key=CASE_KEY, max_chars=32,
            split=True, request_sha256=self.package()['request_sha256'],
            subject_id='mufti-fixture', provider=provider, action=action, note=note,
            command_id='a' * 32, synthetic_fixtures_only=True)
        values.update(changes)
        return self.api().record_decision(**values)

    def stage(self, provider, response):
        return self.api().stage_reviewed_response(self.fixture.directory, case_key=CASE_KEY,
            max_chars=32, split=True, author_id=AUTHOR, response_json=response,
            provider=provider, verifier=self.fixture.verifier, synthetic_fixtures_only=True)

    def test_submission_is_idempotent_and_preserves_original_journal(self):
        before = self.fixture.files()
        first = self.submit()
        self.assertEqual(first, self.submit())
        self.assertEqual(first['state'], 'PENDING_REVIEW')
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(self.fixture.files(), before)

    def test_ready_decision_is_not_a_signature_or_a_delivery_intent(self):
        self.submit()
        result = self.decide(self.provider())
        self.assertEqual(result['state'], 'READY_FOR_SIGNATURE')
        self.assertFalse(result['signed_approval'])
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_pending_review_blocks_even_a_valid_external_receipt(self):
        self.submit()
        with self.assertRaises(ValueError):
            self.stage(self.provider(), self.fixture.signed_response(self.package()))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_matching_human_decision_and_external_signature_stage_only_once(self):
        before = self.fixture.files()
        self.submit()
        provider = self.provider()
        self.decide(provider)
        response = self.fixture.signed_response(self.package())
        result = self.stage(provider, response)
        self.assertEqual(result, self.stage(provider, response))
        self.assertEqual(result['status'], 'STAGED_NOT_SENT')
        self.assertEqual(ApprovalClaim.objects.count(), 1)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        self.assertEqual(self.fixture.files(), before)

    def test_return_for_changes_requires_a_note_and_blocks_staging(self):
        self.submit()
        provider = self.provider()
        with self.assertRaises(ValueError):
            self.decide(provider, action='RETURN_FOR_CHANGES', note='   ')
        result = self.decide(provider, action='RETURN_FOR_CHANGES', note='  راجع هذا المثال.  ')
        self.assertEqual(result['note'], '  راجع هذا المثال.  ')
        with self.assertRaises(ValueError):
            self.stage(provider, self.fixture.signed_response(self.package()))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_declined_request_cannot_be_staged(self):
        self.submit()
        provider = self.provider()
        self.decide(provider, action='DECLINED', note='سبب رفض اصطناعي')
        with self.assertRaises(ValueError):
            self.stage(provider, self.fixture.signed_response(self.package()))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_changed_source_invalidates_a_pending_decision(self):
        request = self.submit()
        provider = self.provider()
        self.fixture.correct_source()
        with self.assertRaises(ValueError):
            self.api().record_decision(directory=self.fixture.directory, case_key=CASE_KEY,
                max_chars=32, split=True, request_sha256=request['request_sha256'],
                subject_id='mufti-fixture', provider=provider, action='READY_FOR_SIGNATURE',
                note='', command_id='a' * 32, synthetic_fixtures_only=True)
        from apps.mufti_review.models import ReviewDecision
        self.assertEqual(ReviewDecision.objects.count(), 0)

    def test_new_human_draft_creates_new_review_without_overwriting_old_decision(self):
        old = self.submit()
        self.decide(self.provider(), action='RETURN_FOR_CHANGES', note='عدّل المثال')
        self.fixture.draft(body=BODY + 'نسخة جديدة')
        self.fixture.note('submit')
        self.fixture.note('confirm')
        new = self.submit()
        self.assertNotEqual(old['request_sha256'], new['request_sha256'])
        self.assertEqual(new['state'], 'PENDING_REVIEW')
        history = self.api().review_history(case_key=CASE_KEY, author_id=AUTHOR, synthetic_fixtures_only=True)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]['state'], 'RETURN_FOR_CHANGES')

    def test_wrong_role_and_unassigned_case_are_rejected_before_sql(self):
        self.submit()
        for change in ({'role': 'AUTHOR'}, {'active': False}, {'case_keys': frozenset({'another'})}):
            provider = self.provider()
            provider.current = replace(provider.current, **change)
            with CaptureQueriesContext(connection) as queries, self.assertRaises(ValueError):
                self.decide(provider)
            self.assertEqual(len(queries), 0)

    def test_identity_expiry_or_outage_cannot_create_a_decision(self):
        self.submit()
        provider = self.provider()
        provider.current = replace(provider.current, valid_until=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            self.decide(provider)
        provider = self.provider()
        provider.unavailable = True
        with self.assertRaises(ValueError):
            self.decide(provider)
        from apps.mufti_review.models import ReviewDecision
        self.assertEqual(ReviewDecision.objects.count(), 0)

    def test_identity_epoch_change_after_decision_blocks_receipt_staging(self):
        self.submit()
        provider = self.provider()
        self.decide(provider)
        provider.current = replace(provider.current, auth_epoch='epoch-2')
        with self.assertRaises(ValueError):
            self.stage(provider, self.fixture.signed_response(self.package()))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_receipt_predating_human_decision_is_rejected(self):
        self.submit()
        provider = self.provider()
        signed_before = self.fixture.signed_response(self.package())
        self.decide(provider)
        with self.assertRaises(ValueError):
            self.stage(provider, signed_before)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_other_mufti_cannot_sign_someone_elses_ready_decision(self):
        self.submit()
        provider = self.provider()
        self.decide(provider)
        signed = self.fixture.signed_response(self.package(), approver_id='other-mufti')
        with self.assertRaises(ValueError):
            self.stage(provider, signed)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_repeat_decision_command_is_idempotent_but_changed_payload_is_not(self):
        self.submit()
        provider = self.provider()
        first = self.decide(provider)
        self.assertEqual(first, self.decide(provider))
        with self.assertRaises(ValueError):
            self.decide(provider, action='DECLINED', note='different')
        from apps.mufti_review.models import ReviewDecision
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_opposing_concurrent_decisions_have_exactly_one_winner(self):
        request = self.submit()
        provider = self.provider()
        api = self.api()
        barrier = Barrier(2, timeout=10)
        def decide(action, command):
            close_old_connections()
            try:
                barrier.wait()
                api.record_decision(directory=self.fixture.directory, case_key=CASE_KEY, max_chars=32,
                    split=True, request_sha256=request['request_sha256'], subject_id='mufti-fixture',
                    provider=provider, action=action, note='سبب اصطناعي', command_id=command,
                    synthetic_fixtures_only=True)
                return 'OK'
            except ValueError:
                return 'DENIED'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(decide, action, command) for action, command in
                [('READY_FOR_SIGNATURE', 'a' * 32), ('DECLINED', 'b' * 32)]]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(results), ['DENIED', 'OK'])

    def test_decision_rows_are_append_only_in_postgresql(self):
        self.submit()
        self.decide(self.provider())
        from apps.mufti_review.models import ReviewDecision
        with self.assertRaises(IntegrityError):
            ReviewDecision.objects.all().update(note='overwritten')
        with self.assertRaises(IntegrityError):
            ReviewDecision.objects.all().delete()
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_production_flag_blocks_submission_before_any_sql(self):
        api = self.api()
        with patch.dict(os.environ, {'FATWA_PRODUCTION': '1'}), CaptureQueriesContext(connection) as queries:
            with self.assertRaises(ValueError):
                api.submit_request(self.fixture.directory, case_key=CASE_KEY, max_chars=32,
                    split=True, author_id=AUTHOR, synthetic_fixtures_only=True)
        self.assertEqual(len(queries), 0)
