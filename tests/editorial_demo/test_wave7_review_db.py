"""E2 PostgreSQL-only locking, atomic review receipts and CLI regressions."""
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import os
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from django.core.management import call_command, CommandError
from django.db import connection, connections, IntegrityError
from django.test.utils import CaptureQueriesContext
from apps.intake_workflow import contracts as c, guards as g, review
from apps.intake_workflow.models import IntakeItem, ReviewEvent
from .wave7_support import OwnedReviewTestCase


class ReviewServiceDatabaseTests(OwnedReviewTestCase):
    def setUp(self):
        self.batch, self.items = self.create_batch()
        self.item = self.items[6]

    def transition(self, item=None, **changes):
        values = dict(operation_id=uuid4(), action='start_review', expected_status='UNREVIEWED',
                      reason='  مراجعة اصطناعية\tبلا اعتماد  ', synthetic_fixtures_only=True)
        return review.transition_review((item or self.item).id, **(values | changes))

    def test_status_and_event_persist_together_without_changing_originals(self):
        before = self.item.original_row
        result = self.transition()
        self.item.refresh_from_db()
        event = ReviewEvent.objects.get(pk=result.event_id)
        self.assertEqual(self.item.review_status, 'IN_REVIEW')
        self.assertEqual(event.from_status, 'UNREVIEWED')
        self.assertEqual(event.to_status, self.item.review_status)
        self.assertEqual(event.reason, '  مراجعة اصطناعية\tبلا اعتماد  ')
        self.assertFalse(result.replayed)
        self.assertEqual(self.item.original_row, before)
        self.assertEqual(self.item.intake_status, 'READY_FOR_EDITOR')
        self.assertEqual(self.item.references.get().reference_status, 'UNVERIFIED')
        connections['default'].close()
        self.assertEqual(IntakeItem.objects.get(pk=self.item.pk).review_status, 'IN_REVIEW')

    def test_exact_replay_after_further_transition_returns_original_event(self):
        operation = uuid4()
        first = self.transition(operation_id=operation)
        self.transition(action='request_changes', expected_status='IN_REVIEW', reason='تصحيح اصطناعي')
        replay = self.transition(operation_id=operation)
        self.assertEqual(replay.event_id, first.event_id)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.to_status, 'IN_REVIEW')
        self.item.refresh_from_db()
        self.assertEqual(self.item.review_status, 'NEEDS_CHANGES')
        self.assertEqual(ReviewEvent.objects.count(), 2)

    def test_conflicting_operation_repeat_fails_closed(self):
        operation = uuid4()
        self.transition(operation_id=operation)
        for change in ({'reason': 'different'}, {'expected_status': 'IN_REVIEW'}, {'action': 'request_changes'}):
            with self.subTest(change=change), self.assertRaises(review.ReviewConflict):
                self.transition(operation_id=operation, **change)
        self.assertEqual(ReviewEvent.objects.count(), 1)

    def test_legal_transition_cycle_and_completion_are_only_internal(self):
        self.transition()
        self.transition(action='request_changes', expected_status='IN_REVIEW')
        self.transition(expected_status='NEEDS_CHANGES')
        result = self.transition(action='complete_review', expected_status='IN_REVIEW')
        self.assertEqual(result.to_status, 'REVIEWED_INTERNAL')
        with self.assertRaises(c.ContractError):
            self.transition(expected_status='REVIEWED_INTERNAL')
        self.assertEqual(ReviewEvent.objects.count(), 4)

    def test_illegal_actions_stale_status_and_invalid_uuid_do_not_write(self):
        for values in ({'action': 'publish'}, {'action': 'approve'}, {'action': 'complete_review'},
                       {'operation_id': 'not-a-uuid'}):
            with self.subTest(values=values), self.assertRaises(c.ContractError):
                self.transition(**values)
        self.transition()
        with self.assertRaises(review.ReviewConflict):
            self.transition()
        with self.assertRaises(review.ReviewNotFound):
            review.transition_review(uuid4(), operation_id=uuid4(), action='start_review',
                expected_status='UNREVIEWED', reason='synthetic', synthetic_fixtures_only=True)
        self.assertEqual(ReviewEvent.objects.count(), 1)

    def test_reason_bounds_and_exact_length(self):
        for reason in ('', ' \t\n', 'x'*2001, None, '\ud800', 'x\x00y'):
            with self.subTest(reason=repr(reason)), self.assertRaises(c.ContractError):
                self.transition(reason=reason)
        self.transition(reason='x'*2000)
        self.assertEqual(len(ReviewEvent.objects.get().reason), 2000)

    def test_guard_rejects_before_transaction_and_writes(self):
        for env, ack in (({'FATWA_WAVE7_SYNTHETIC_WRITES':'0'}, True),
                         ({'FATWA_PRODUCTION':'1'}, True), ({}, False)):
            with self.subTest(env=env,ack=ack), patch.dict(os.environ, env), \
                 patch.object(g.transaction, 'atomic') as atomic:
                with self.assertRaises(g.SyntheticWriteDenied):
                    self.transition(synthetic_fixtures_only=ack)
                atomic.assert_not_called()
        self.assertEqual(ReviewEvent.objects.count(), 0)

    def test_no_outer_atomic_may_precede_guard(self):
        from django.db import transaction
        with transaction.atomic(), self.assertRaises(g.SyntheticWriteDenied):
            self.transition()
        self.assertEqual(ReviewEvent.objects.count(), 0)

    def test_event_failure_rolls_back_status(self):
        with patch('django.db.models.query.QuerySet.create', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.transition()
        self.item.refresh_from_db()
        self.assertEqual(self.item.review_status, 'UNREVIEWED')
        self.assertEqual(ReviewEvent.objects.count(), 0)

    def test_events_remain_append_only(self):
        result = self.transition()
        for mutation in (lambda: ReviewEvent.objects.filter(pk=result.event_id).update(reason='rewritten'),
                         lambda: ReviewEvent.objects.filter(pk=result.event_id).delete()):
            with self.assertRaises(IntegrityError), g.synthetic_atomic(synthetic_fixtures_only=True):
                mutation()
        self.assertEqual(ReviewEvent.objects.get().reason, '  مراجعة اصطناعية\tبلا اعتماد  ')

    def test_same_operation_concurrency_has_one_event_and_one_replay(self):
        barrier = Barrier(2)
        operation = uuid4()
        def run():
            try:
                barrier.wait(timeout=10)
                return self.transition(operation_id=operation)
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertCountEqual([r.replayed for r in results], [False, True])
        self.assertEqual(len({r.event_id for r in results}), 1)
        self.assertEqual(ReviewEvent.objects.count(), 1)

    def test_concurrent_distinct_operations_do_not_overwrite_stale_status(self):
        barrier = Barrier(2)
        def run():
            try:
                barrier.wait(timeout=10)
                try:
                    self.transition()
                    return 'created'
                except review.ReviewConflict:
                    return 'conflict'
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(lambda _: run(), range(2))), ['created', 'conflict'])
        self.assertEqual(ReviewEvent.objects.count(), 1)

    def test_same_external_id_or_operation_in_another_batch_is_isolated(self):
        _, other = self.create_batch()
        operation = uuid4()
        one = self.transition(operation_id=operation)
        two = self.transition(item=other[6], operation_id=operation)
        self.assertNotEqual(one.item_id, two.item_id)
        self.assertNotEqual(one.event_id, two.event_id)
        self.assertEqual(ReviewEvent.objects.count(), 2)

    def test_cli_calls_service_without_outer_transaction_and_replays(self):
        output = StringIO()
        operation = str(uuid4())
        args = ['--item', str(self.item.id), '--operation', operation, '--action', 'start_review',
                '--expected-status', 'UNREVIEWED', '--reason', 'CLI synthetic', '--synthetic-fixtures-only']
        call_command('wave7_review', *args, stdout=output)
        self.assertIn('"replayed": false', output.getvalue())
        output = StringIO()
        call_command('wave7_review', *args, stdout=output)
        self.assertIn('"replayed": true', output.getvalue())
        self.assertEqual(ReviewEvent.objects.count(), 1)

    def test_cli_missing_ack_or_flag_fails_without_echoing_reason(self):
        with self.assertRaises(CommandError) as caught:
            call_command('wave7_review', '--item', str(self.item.id), '--operation', str(uuid4()),
                         '--action', 'start_review', '--expected-status', 'UNREVIEWED', '--reason', 'DO_NOT_ECHO')
        self.assertNotIn('DO_NOT_ECHO', str(caught.exception))
        self.assertEqual(ReviewEvent.objects.count(), 0)
