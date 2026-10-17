"""E2 persisted GET-only worklist and exact-source read regressions; PG17/18 only."""
import json
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from django.db import connection, connections
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from apps.intake_workflow import contracts as c, fixtures as f, guards as g, review
from apps.intake_workflow.models import IntakeBatch, IntakeItem, ReviewEvent
from .wave7_support import OwnedReviewTestCase


@override_settings(WAVE7_REVIEW_READ_ENABLED=True, ROOT_URLCONF='tests.editorial_demo.wave7_urls')
class PersistentReadDatabaseTests(OwnedReviewTestCase):
    url = '/dev/editorial-preview/persisted'

    def setUp(self):
        self.batch, self.items = self.create_batch()

    def load(self, **kwargs):
        return review.load_review_worklist(batch_id=self.batch.id, synthetic_fixtures_only=True, **kwargs)

    def get(self, data=None, method='get'):
        return getattr(self.client, method)(self.url, data or {}, HTTP_HOST='localhost')

    def test_uuid_detail_and_sources_survive_connections_restart(self):
        row = self.load(row_id=self.items[0].id).row
        self.assertEqual(row.question, f.ORIGINAL_QUESTION)
        self.assertEqual(row.original_row, self.items[0].original_row)
        raw = bytes(self.batch.original_payload)
        self.assertEqual(raw[row.source_byte_start:row.source_byte_end], row.original_row.encode())
        pointer = row.references[0]
        self.assertEqual(raw[pointer.source_byte_start:pointer.source_byte_end], pointer.original_pointer.encode())
        connections['default'].close()
        again = self.load(row_id=self.items[0].id).row
        self.assertEqual(again, row)

    def test_fresh_python_process_reads_committed_status_and_exact_source(self):
        review.transition_review(self.items[6].id,operation_id=uuid4(),action='start_review',
            expected_status='UNREVIEWED',reason='Synthetic restart probe',synthetic_fixtures_only=True)
        code = '''import sys, django
django.setup()
from django.conf import settings
from django.db import connections
from apps.intake_workflow.review import load_review_worklist
connections['default'].settings_dict['NAME'] = settings.WAVE7_TEST_DATABASE_NAME
row = load_review_worklist(batch_id=sys.argv[1],row_id=sys.argv[2],synthetic_fixtures_only=True).row
assert row.review_status == 'IN_REVIEW'
sys.stdout.buffer.write(row.original_row.encode('utf-8'))
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.batch.id),str(self.items[6].id)],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=True)
        self.assertEqual(result.stdout,self.items[6].original_row.encode('utf-8'))

    def test_read_preserves_numeric_lexemes_and_null_without_float_decode(self):
        raw = b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":[ {"external_id":73.000000000000001,"question":null,"reference_links":[1e-20000,null]} ,null]}'
        batch, items = self.create_batch(raw)
        result = review.load_review_worklist(batch_id=batch.id, row_id=items[0].id, synthetic_fixtures_only=True)
        self.assertIn('73.000000000000001', result.row.original_row)
        self.assertIsNone(result.row.external_id)
        self.assertIsNone(result.row.question)
        self.assertEqual([r.original_pointer for r in result.row.references], ['1e-20000', 'null'])
        self.assertEqual(result.rows[1].original_row, 'null')
        self.assertTrue(all(not ref.citation_text for ref in result.row.references))

    def test_duplicate_external_ids_and_cross_batch_rows_never_collide(self):
        other, rows = self.create_batch()
        one = self.load(row_id=self.items[0].id).row
        two = self.load(row_id=self.items[3].id).row
        self.assertEqual(one.external_id, two.external_id)
        self.assertNotEqual(one.id, two.id)
        self.assertNotEqual(one.question, two.question)
        with self.assertRaises(review.ReviewNotFound):
            self.load(row_id=rows[0].id)
        self.assertEqual(self.get({'batch': str(self.batch.id), 'row': str(rows[0].id)}).status_code, 404)

    def test_filters_page_detail_and_return_state_are_native_get_links(self):
        params = {'batch': str(self.batch.id), 'intake_status': 'BLOCKED_INVALID', 'review_status': 'UNREVIEWED',
                  'page_size': '1', 'page': '2', 'q': 'اصطناعي'}
        response = self.get(params)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'wave7-persisted')
        detail_url = response.context['stored_display_rows'][0]['detail_url']
        detail = self.client.get(detail_url, HTTP_HOST='localhost')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context['stored'].row.id, response.context['stored'].rows[0].id)
        returned = self.client.get(detail.context['stored_return_url'], HTTP_HOST='localhost')
        self.assertEqual(returned.context['stored'].rows, response.context['stored'].rows)
        self.assertEqual(parse_qs(urlsplit(detail.context['stored_return_url']).query), {k:[v] for k,v in params.items()})
        self.assertNotContains(detail, 'method="post"')
        self.assertNotContains(detail, '<textarea')
        self.assertNotContains(detail, '<video')
        self.assertNotContains(detail, 'href="https://example.invalid')

    def test_read_is_not_a_review_transition_or_reference_verification(self):
        before = [m.objects.count() for m in (IntakeBatch, IntakeItem, ReviewEvent)]
        for verb in ('get', 'head', 'post', 'put', 'patch', 'delete'):
            response = self.get({'batch':str(self.batch.id)}, method=verb)
            self.assertEqual(response.status_code, 200 if verb in ('get','head') else 405)
        self.assertEqual([m.objects.count() for m in (IntakeBatch, IntakeItem, ReviewEvent)], before)
        self.assertEqual(set(IntakeItem.objects.values_list('review_status', flat=True)), {'UNREVIEWED'})

    def test_feature_local_and_production_guards_reject_before_orm(self):
        for values in ({'WAVE7_REVIEW_READ_ENABLED':False}, {'FATWA_PRODUCTION':True}):
            with override_settings(**values), CaptureQueriesContext(connection) as queries:
                response = self.get()
            self.assertEqual(response.status_code,404)
            self.assertEqual(len(queries),0)
        with CaptureQueriesContext(connection) as queries:
            response=self.client.get(self.url,HTTP_HOST='localhost',REMOTE_ADDR='192.0.2.1')
        self.assertEqual(response.status_code,404)
        self.assertEqual(len(queries),0)

    def test_bad_parameters_reject_before_database_processing(self):
        bad = ({'row':str(self.items[0].id)}, {'batch':'private/path'}, {'q':'x'*81}, {'q':'\x00'},
               {'page':'0'}, {'page_size':'51'}, {'review_status':'APPROVED'}, {'intake_status':'VERIFIED'},
               {'batch':[str(self.batch.id),str(self.batch.id)]}, {'upload':'private'})
        for params in bad:
            with self.subTest(params=params),CaptureQueriesContext(connection) as queries:
                response=self.get(params)
            self.assertEqual(response.status_code,400)
            self.assertEqual(len(queries),0)
            self.assertEqual(response['Cache-Control'],'no-store')

    def test_unknown_batch_row_and_page_fail_closed(self):
        for params in ({'batch':str(uuid4())}, {'batch':str(self.batch.id),'row':str(uuid4())},
                       {'batch':str(self.batch.id),'page':'10000'}, {'batch':str(self.batch.id),'q':'no-match','page':'2'}):
            self.assertEqual(self.get(params).status_code,404)
        self.assertContains(self.get({'batch':str(self.batch.id),'q':'no-match'}),'لا توجد سجلات مطابقة')

    def test_persisted_history_and_stored_citations_are_escaped_not_approval(self):
        f.seed_reference_catalog(synthetic_fixtures_only=True)  # own guarded unit, no outer transaction
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            self.items[6].references.update(reference_status='VERIFIED',
                verified_identity=dict(c.VERIFIED_IDENTITIES[1]),citation_text='مرجع <اصطناعي> & فقط')
        result=review.transition_review(self.items[6].id,operation_id=uuid4(),action='start_review',expected_status='UNREVIEWED',
            reason='<script>synthetic</script>',synthetic_fixtures_only=True)
        response=self.get({'batch':str(self.batch.id),'row':str(self.items[6].id)})
        self.assertContains(response,'&lt;script&gt;synthetic&lt;/script&gt;')
        self.assertNotContains(response,'<script>synthetic</script>')
        self.assertContains(response,'مرجع &lt;اصطناعي&gt; &amp; فقط')
        self.assertNotContains(response,'مرجع <اصطناعي>')
        self.assertContains(response,'لا توجد إجابة أو اعتماد شرعي أو نشر')
        self.assertEqual(response.context['stored'].row.events[0].id,result.event_id)

    def test_detail_history_is_bounded_and_explicitly_marks_older_events(self):
        status='UNREVIEWED'
        for n in range(101):
            action='request_changes' if status=='IN_REVIEW' else 'start_review'
            result=review.transition_review(self.items[6].id,operation_id=uuid4(),action=action,
                expected_status=status,reason='Synthetic history '+str(n),synthetic_fixtures_only=True)
            status=result.to_status
        detail=self.load(row_id=self.items[6].id).row
        self.assertEqual(len(detail.events),100)
        self.assertTrue(detail.events_truncated)
        self.assertEqual(ReviewEvent.objects.count(),101)
        self.assertTrue(all(not row.events for row in self.load().rows))

    def test_database_failure_is_sanitized_and_no_store(self):
        from django.db import DatabaseError
        with patch.object(review,'load_review_worklist',side_effect=DatabaseError('DSN_SECRET')):
            response=self.get()
        self.assertEqual(response.status_code,503)
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertNotContains(response,'DSN_SECRET',status_code=503)
