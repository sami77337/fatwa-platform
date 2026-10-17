"""Actual E4 read-service/API/SSR compatibility; runner-owned PG only."""
import json
import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from django.test import RequestFactory, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.reference import views as reference_views
from apps.intake_workflow import contracts as c, fixtures as f, guards as g, review
from .wave7_support import OwnedReviewTestCase


@override_settings(WAVE7_READS_ENABLED=True, ROOT_URLCONF='tests.editorial_demo.wave7_urls')
class E4AdapterDatabaseTests(OwnedReviewTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'FATWA_WAVE7_SYNTHETIC_READS':'1'})
        env.start(); self.addCleanup(env.stop)
        self.batch, self.items = self.create_batch()

    def test_actual_api_context_and_editorial_modes_have_same_results(self):
        for mode, text, expected in [('exact','سؤال اصطناعي',[3]),
                                     ('literal','سؤال اصطناعي',[2,3]),
                                     ('normalized','سُؤَال اصطناعي',[1,2,3,7])]:
            with self.subTest(mode=mode):
                query = {'batch':str(self.batch.id),'q':text,'mode':mode,'limit':'2','offset':'0',
                         'intake_status':'BLOCKED_INVALID','review_status':'UNREVIEWED'}
                request = RequestFactory().get('/dev/wave7/api/items',query,HTTP_HOST='localhost')
                response = reference_views.api_workflow_items(request)
                self.assertEqual(response.status_code,200)
                api = json.loads(response.content)
                context = reference_views.workflow_read_context(request)
                stored = review.load_review_worklist(batch_id=self.batch.id,q=text,mode=mode,
                    intake_status='BLOCKED_INVALID',review_status='UNREVIEWED',page_size=2,
                    synthetic_fixtures_only=True)
                expected = [n for n in expected if n != 7]
                self.assertEqual([r.row_ordinal for r in stored.rows],expected[:2])
                self.assertEqual([str(r.id) for r in stored.rows],[r['id'] for r in api['items']])
                self.assertEqual([str(r.id) for r in stored.rows],[r.id for r in context['workflow_page'].items])
                self.assertEqual(stored.matched_count,api['count'])
                self.assertEqual(stored.mode,mode)

    def test_mode_batch_filters_and_page_survive_detail_return_reload(self):
        params={'batch':str(self.batch.id),'q':'سُؤَال اصطناعي','mode':'normalized',
                'intake_status':'BLOCKED_INVALID','review_status':'UNREVIEWED','page_size':'1','page':'2'}
        response=self.client.get('/dev/editorial-preview/persisted',params,HTTP_HOST='localhost')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'id="stored-mode"')
        detail=self.client.get(response.context['stored_display_rows'][0]['detail_url'],HTTP_HOST='localhost')
        self.assertEqual(detail.status_code,200)
        back=detail.context['stored_return_url']
        self.assertEqual(parse_qs(urlsplit(back).query),{k:[v] for k,v in params.items()})
        for _ in range(2):
            returned=self.client.get(back,HTTP_HOST='localhost')
            self.assertEqual(returned.context['stored'].rows,response.context['stored'].rows)

    def test_current_reference_state_replaces_intake_snapshot(self):
        f.seed_reference_catalog(synthetic_fixtures_only=True)
        target=self.items[6]
        def load():
            return review.load_review_worklist(batch_id=self.batch.id,row_id=target.id,
                                               synthetic_fixtures_only=True).row
        self.assertEqual(load().references[0].reference_status,'UNVERIFIED')
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            target.references.update(reference_status='VERIFIED',verified_identity=dict(c.VERIFIED_IDENTITIES[1]),
                                     citation_text='مرجع اصطناعي <حالي>')
        request=RequestFactory().get('/',{'batch':str(self.batch.id)},HTTP_HOST='localhost')
        detail=reference_views.workflow_read_context(request,item_id=str(target.id))['workflow_item']
        self.assertEqual(load().references[0].citation_text,detail.references[0].citation_text)
        self.assertEqual(load().references[0].citation_text,'مرجع اصطناعي <حالي>')
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            target.references.update(reference_status='MISMATCHED',verified_identity={},citation_text='')
        self.assertEqual(load().references[0].reference_status,'MISMATCHED')
        self.assertFalse(load().references[0].citation_text)
        self.assertEqual(load().intake_status,'READY_FOR_EDITOR')

    def test_invalid_mode_offset_and_bounded_normalized_search_fail_closed(self):
        url='/dev/editorial-preview/persisted'
        for params in ({'mode':'fuzzy'},{'page':'402','page_size':'50'}):
            with CaptureQueriesContext(connection) as queries:
                response=self.client.get(url,{'batch':str(self.batch.id),**params},HTTP_HOST='localhost')
            self.assertEqual(response.status_code,400)
            self.assertEqual(len(queries),0)
        with patch('apps.reference.services.WORKFLOW_MAX_SEARCH_ROWS',1):
            response=self.client.get(url,{'batch':str(self.batch.id),'q':'اصطناعي','mode':'normalized'},HTTP_HOST='localhost')
        self.assertEqual(response.status_code,400)
        self.assertNotContains(response,'Traceback',status_code=400)

    def test_unified_flags_and_environment_fail_before_sql(self):
        for setting, environment in [(False,'1'),(True,'0')]:
            with override_settings(WAVE7_READS_ENABLED=setting,WAVE7_REVIEW_READ_ENABLED=True), \
                 patch.dict(os.environ,{'FATWA_WAVE7_SYNTHETIC_READS':environment}), \
                 CaptureQueriesContext(connection) as queries:
                response=self.client.get('/dev/editorial-preview/persisted',HTTP_HOST='localhost')
            self.assertEqual(response.status_code,404)
            self.assertEqual(len(queries),0)

    def test_external_id_is_not_an_e4_question_search_alias(self):
        stored=review.load_review_worklist(batch_id=self.batch.id,q=self.items[0].external_id,
                    mode='literal',synthetic_fixtures_only=True)
        self.assertEqual(stored.matched_count,0)

    def test_list_projection_has_bounded_queries_without_detail_per_item(self):
        counts=[]
        for size in (1,8):
            with CaptureQueriesContext(connection) as queries:
                result=review.load_review_worklist(batch_id=self.batch.id,page_size=size,
                                                  synthetic_fixtures_only=True)
            self.assertEqual(len(result.rows),size)
            self.assertTrue(all(query['sql'].lstrip().split()[0].upper() in ('SELECT','SHOW') for query in queries))
            counts.append(len(queries))
        self.assertEqual(counts[0],counts[1])
        self.assertLessEqual(counts[1],20)
        print('E2_ADAPTER_LIST_QUERY_COUNTS',counts)

    def test_actual_read_guard_failure_is_sanitized_503_without_queries(self):
        with patch.dict(os.environ,{'FATWA_WAVE7_SYNTHETIC_WRITES':'0'}), CaptureQueriesContext(connection) as queries:
            response=self.client.get('/dev/editorial-preview/persisted',HTTP_HOST='localhost')
        self.assertEqual(response.status_code,503)
        self.assertEqual(len(queries),0)
        self.assertNotContains(response,'WRITES_DISABLED',status_code=503)
        self.assertNotContains(response,'Traceback',status_code=503)
        self.assertEqual(response['Cache-Control'],'no-store')
