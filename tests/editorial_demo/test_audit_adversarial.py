"""Independent adversarial HTTP/export checks using fabricated immutable DTOs.

Fixture identity: audit-adversarial-dto-v1. The reader alone is replaced; real
guards, query parsing, timeline/export code and Django responses run. These are
SimpleTestCase checks, not PostgreSQL or original-source acceptance evidence.
"""

import json
import os
from dataclasses import asdict, replace
from datetime import datetime
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings

from apps.editorial_demo import workflow_audit
from apps.intake_workflow import guards, review


@override_settings(
    ROOT_URLCONF='config.wave7_urls',
    WAVE7_READS_ENABLED=True,
    INSTALLED_APPS=[*settings.INSTALLED_APPS, 'apps.intake_workflow'],
)
class AuditAdversarialTests(SimpleTestCase):
    url = '/dev/editorial-preview/workflow-audit?format=json'

    def setUp(self):
        env = patch.dict(os.environ, FATWA_PRODUCTION='0', FATWA_WAVE7_SYNTHETIC_READS='1')
        env.start()
        self.addCleanup(env.stop)
        self.source = ' \r\nأ | أ | 🙂 | \u200f | \u2028\u2029 | " <>& \\ \t '
        self.source_bytes = b'fixture-prefix\n' + self.source.encode('utf-8') + b'\nfixture-suffix'
        self.start = len(b'fixture-prefix\n')
        self.end = self.start + len(self.source.encode('utf-8'))
        refs = (
            review.StoredReference(UUID(int=22), self.source, self.start, self.end,
                                   'MISMATCHED', '  استشهاد حالي\r\n🙂  '),
            review.StoredReference(UUID(int=21), 'أ ≠ أ', 101, 114, 'UNVERIFIED', ''),
        )
        events = tuple(
            review.StoredReviewEvent(UUID(int=event), UUID(int=operation), action, before,
                                     after, self.source, datetime.fromisoformat(when))
            for event, operation, action, before, after, when in (
                (33, 43, 'start_review', 'NEEDS_CHANGES', 'IN_REVIEW',
                 '2026-10-22T10:00:00.987654+01:00'),
                (32, 42, 'request_changes', 'IN_REVIEW', 'NEEDS_CHANGES',
                 '2026-10-22T07:00:00-01:00'),
                (31, 41, 'start_review', 'UNREVIEWED', 'IN_REVIEW',
                 '2026-10-22T09:30:00+02:00'),
            )
        )
        row = review.StoredReviewRow(
            UUID(int=11), UUID(int=1), 7, 'synthetic-adversarial-🙂', self.source,
            self.source, self.start, self.end, 'READY_FOR_EDITOR', 'IN_REVIEW', None,
            refs, events, True,
        )
        self.stored = review.ReviewWorklist(
            (review.ReviewBatchOption(UUID(int=1),
                                     datetime.fromisoformat('2026-10-22T08:00:00+00:00')),),
            UUID(int=1), (), row, 9, 3, 2, 3, 1, 'أ أ', 'literal', '', '',
        )

    def request(self, method='get', *, url=None):
        return getattr(self.client, method)(
            url or self.url, HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1',
        )

    def test_exact_utf8_byte_ceiling_is_inclusive_but_one_more_byte_fails_closed(self):
        # Catch >= instead of >, character-count limits, and partial truncation.
        # Measure fixed envelope overhead, then add independently counted UTF-8
        # bytes to a single selected field (the page deliberately has no rows).
        empty = replace(self.stored, row=replace(self.stored.row, original_row=''))
        with patch.object(review, 'load_review_worklist', return_value=empty):
            envelope = self.request()
        self.assertEqual(envelope.status_code, 200)
        limit = workflow_audit.MAX_AUDIT_JSON_BYTES
        pairs, remaining = divmod(limit - len(envelope.content), 2)
        text = 'ع' * pairs + 'x' * remaining
        exact = replace(empty, row=replace(empty.row, original_row=text))
        before = asdict(exact)
        with patch.object(review, 'load_review_worklist', return_value=exact):
            response = self.request()
            head = self.request('head')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.content), limit)
        self.assertLess(len(response.content.decode('utf-8')), limit)
        self.assertEqual(response.json()['worklist']['row']['original_row'], text)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')
        self.assertEqual(head['Content-Length'], str(limit))
        self.assertEqual(asdict(exact), before)

        oversized = replace(exact, row=replace(exact.row, original_row=text + 'x'))
        rejected_before = asdict(oversized)
        with patch.object(review, 'load_review_worklist', return_value=oversized):
            rejected = self.request()
            rejected_head = self.request('head')
        self.assertEqual(rejected.status_code, 503)
        self.assertEqual(rejected['Cache-Control'], 'no-store')
        self.assertNotIn(('ع' * 32).encode('utf-8'), rejected.content)
        self.assertNotIn(b'"worklist"', rejected.content)
        self.assertEqual(rejected_head.status_code, 503)
        self.assertEqual(rejected_head.content, b'')
        self.assertEqual(rejected_head['Content-Length'], rejected['Content-Length'])
        self.assertEqual(asdict(oversized), rejected_before)

    def test_export_retains_raw_source_and_current_refs_when_utc_order_crosses_batch(self):
        # Catch Unicode normalization/stripping, reference sorting, UTC rewriting,
        # a fixed batch-first assumption, or sorting the stored event window.
        before = asdict(self.stored)
        with patch.object(review, 'load_review_worklist', return_value=self.stored):
            response = self.request()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        row = data['worklist']['row']
        self.assertEqual(row['original_row'].encode('utf-8'),
                         self.source_bytes[row['source_byte_start']:row['source_byte_end']])
        self.assertEqual(row['question'], self.source)
        self.assertEqual(row['external_id'], 'synthetic-adversarial-🙂')
        self.assertIsNone(row['prepared_clip_url'])
        self.assertEqual([ref['id'] for ref in row['references']],
                         [str(UUID(int=22)), str(UUID(int=21))])
        self.assertEqual(row['references'][0]['original_pointer'], self.source)
        self.assertEqual(row['references'][0]['citation_text'], '  استشهاد حالي\r\n🙂  ')
        self.assertEqual(row['references'][1]['original_pointer'], 'أ ≠ أ')
        self.assertEqual(row['references'][1]['citation_text'], '')
        self.assertEqual([event['id'] for event in row['events']],
                         [str(UUID(int=33)), str(UUID(int=32)), str(UUID(int=31))])
        self.assertEqual([entry['kind'] for entry in data['timeline']],
                         ['review', 'batch', 'review', 'review'])
        self.assertEqual([entry['source']['id'] for entry in data['timeline']],
                         [str(UUID(int=31)), str(UUID(int=1)), str(UUID(int=32)), str(UUID(int=33))])
        self.assertEqual([entry['source']['created_at'] for entry in data['timeline']], [
            '2026-10-22T09:30:00+02:00', '2026-10-22T08:00:00+00:00',
            '2026-10-22T07:00:00-01:00', '2026-10-22T10:00:00.987654+01:00',
        ])
        for entry, operation in zip((data['timeline'][0], *data['timeline'][2:]), (41, 42, 43)):
            self.assertEqual(entry['source']['operation_id'], str(UUID(int=operation)))
            self.assertEqual(entry['source']['reason'], self.source)
        self.assertTrue(row['events_truncated'])
        self.assertFalse(data['complete_history'])
        self.assertTrue(data['references_are_current_state'])
        self.assertFalse(data['batch_timestamp_is_row_intake_time'])
        self.assertEqual(data['worklist']['rows'], [])
        self.assertEqual((data['worklist']['page'], data['worklist']['page_count']), (2, 3))
        self.assertEqual(asdict(self.stored), before)

    def test_encoded_duplicate_filters_reject_get_and_head_before_reader(self):
        # QueryDict decoding must not permit aliases or equal duplicates to pick
        # one identity/filter silently. These extend beyond format/batch/page.
        queries = (
            'row=a&%72ow=a', 'q=a&%71=a', 'mode=literal&mode=literal',
            'intake_status=&intake_status=', 'review_status=&review_status=',
            'page_size=1&page_size=1', 'q%5B%5D=private-sentinel',
        )
        for query in queries:
            with self.subTest(query=query), patch.object(review, 'load_review_worklist') as reader:
                get = self.request(url=self.url + '&' + query)
                head = self.request('head', url=self.url + '&' + query)
                self.assertEqual(get.status_code, 400)
                self.assertEqual(head.status_code, 400)
                self.assertEqual(head.content, b'')
                self.assertEqual(head['Cache-Control'], 'no-store')
                self.assertEqual(head['Content-Type'], get['Content-Type'])
                self.assertEqual(head['Content-Length'], get['Content-Length'])
                self.assertNotIn(b'private-sentinel', get.content)
                reader.assert_not_called()

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2)
    def test_query_field_count_denial_is_sanitized_before_reader_for_head_too(self):
        with patch.object(review, 'load_review_worklist') as reader:
            get = self.request(url=self.url + '&q=private-sentinel&mode=literal')
            head = self.request('head', url=self.url + '&q=private-sentinel&mode=literal')
        self.assertEqual(get.status_code, 400)
        self.assertNotIn(b'private-sentinel', get.content)
        self.assertEqual(head.status_code, 400)
        self.assertEqual(head.content, b'')
        self.assertEqual(head['Cache-Control'], 'no-store')
        self.assertEqual(head['Content-Length'], get['Content-Length'])
        reader.assert_not_called()

    def test_reader_exception_details_never_enter_export_or_head_error_body(self):
        secret = 'private-sentinel <script>\r\n🙂'
        for error, status in (
            (ValueError(secret), 400),
            (review.ReviewNotFound(secret), 404),
            (review.ReviewUnavailable(secret), 503),
            (guards.SyntheticWriteDenied(secret), 503),
            (DatabaseError(secret), 503),
        ):
            with self.subTest(error=type(error).__name__), patch.object(
                review, 'load_review_worklist', side_effect=error,
            ):
                get = self.request()
                head = self.request('head')
                self.assertEqual(get.status_code, status)
                self.assertNotIn(b'private-sentinel', get.content)
                self.assertNotIn(b'<script>', get.content)
                self.assertNotIn(b'"worklist"', get.content)
                self.assertEqual(head.status_code, status)
                self.assertEqual(head.content, b'')
                self.assertEqual(head['Cache-Control'], 'no-store')
                self.assertEqual(head['Content-Type'], get['Content-Type'])
                self.assertEqual(head['Content-Length'], get['Content-Length'])

    def test_json_query_and_override_header_cannot_turn_mutation_into_safe_export(self):
        body = json.dumps({'action': 'start_review', 'reason': 'private-sentinel'})
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            with self.subTest(method=method), patch.object(review, 'load_review_worklist') as reader:
                response = self.client.generic(
                    method, self.url, data=body, content_type='application/json',
                    HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1',
                    HTTP_X_HTTP_METHOD_OVERRIDE='GET',
                )
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response['Allow'], 'GET, HEAD')
                self.assertNotIn(b'private-sentinel', response.content)
                self.assertNotIn(b'"worklist"', response.content)
                reader.assert_not_called()
                # Do not impose an empty body or view-level cache guarantee on
                # framework/middleware denials that occur before the view.
