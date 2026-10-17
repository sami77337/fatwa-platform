"""Explicit Wave7 PG-only label; filename intentionally outside legacy test_*.py discovery.

Run tests.integration.ui.wave7_workflow_reads_db with wave7_test settings only.
"""
import hashlib
import json
import os
from dataclasses import asdict
from time import perf_counter
from uuid import uuid4
from unittest.mock import patch

from django.conf import settings
from django.db import connection, connections, DatabaseError
from django.test import TransactionTestCase, override_settings, RequestFactory
from django.test.utils import CaptureQueriesContext

from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference
from apps.reference import services, views
from apps.reference.query import InvalidQuery, Page


@override_settings(WAVE7_READS_ENABLED=True)
class Wave7WorkflowReadDatabaseTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        target = g.require_synthetic_write(synthetic_fixtures_only=True)
        if target.database_name != settings.WAVE7_TEST_DATABASE_NAME:
            raise RuntimeError('E4 reads tests require exact runner-owned test database')

    def persist(self, raw=None):
        raw = f.synthetic_payload() if raw is None else raw
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = IntakeBatch.objects.create(idempotency_key=uuid4().hex,
                original_payload=raw, payload_sha256=hashlib.sha256(raw).hexdigest())
            items = []
            for ordinal, (row, source) in enumerate(zip(parsed.items, parsed.item_sources), 1):
                question = row.get('question') if isinstance(row, dict) else None
                item = IntakeItem.objects.create(batch=batch, row_ordinal=ordinal,
                    external_id=c.valid_external_id(row.get('external_id')) if isinstance(row, dict) else None,
                    question_original=question if isinstance(question, str) else None,
                    original_row=source.text, source_byte_start=source.start, source_byte_end=source.end,
                    intake_status='READY_FOR_EDITOR' if ordinal == 1 else 'BLOCKED_INVALID' if ordinal in (3,8) else 'NEEDS_REVIEW',
                    review_status='IN_REVIEW' if ordinal == 2 else 'UNREVIEWED')
                items.append(item)
                for n, pointer in enumerate(parsed.reference_sources[ordinal-1], 1):
                    IntakeReference.objects.create(intake_item=item, reference_ordinal=n,
                        original_pointer=pointer.text, source_byte_start=pointer.start, source_byte_end=pointer.end)
        return batch, items

    def setUp(self):
        self.env = patch.dict(os.environ, {'FATWA_WAVE7_SYNTHETIC_READS':'1'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.one, self.items = self.persist()
        self.two, self.other = self.persist()

    def read(self, **query):
        return services.workflow_items(synthetic_fixtures_only=True, **query)

    def request(self, path='/dev/wave7/api/items', **query):
        return RequestFactory().get(path, query, HTTP_HOST='127.0.0.1', REMOTE_ADDR='127.0.0.1')

    def test_persistent_browse_filter_only_paging_uuid_and_reopen(self):
        result = self.read(page=Page(3))
        self.assertEqual((result.total, result.limit, result.offset, result.next_offset), (16,3,0,3))
        ids = []
        for offset in range(0,16,3):
            ids += [row.id for row in self.read(page=Page(3,offset)).items]
        self.assertEqual(ids, [str(row.pk) for row in self.items+self.other])
        connection.close()
        self.assertEqual([row.id for row in self.read(page=Page(3)).items], ids[:3])
        data = self.read(batch_id=str(self.one.pk), intake_status='READY_FOR_EDITOR')
        self.assertEqual([row.id for row in data.items], [str(self.items[0].pk)])
        self.assertEqual(self.read(batch_id=self.one.pk, review_status='IN_REVIEW').total, 1)
        self.assertEqual(self.read(batch_id=self.one.pk, page=Page(20,10)).items, ())
        self.assertEqual(self.read(batch_id=self.one.pk, text='غائب').total, 0)
        self.assertEqual(self.read(batch_id=self.one.pk, text='َـ').total, 0)

    def test_same_question_modes_and_batch_search_match(self):
        for mode, text, ordinals in [('exact','سؤال اصطناعي',[3]),
                                      ('literal','سؤال اصطناعي',[2,3]),
                                      ('normalized','سُؤَال اصطناعي',[1,2,3,7])]:
            with self.subTest(mode=mode):
                result = self.read(batch_id=self.one.pk, mode=mode, text=text)
                self.assertEqual([r.row_ordinal for r in result.items], ordinals)
                batches = services.workflow_batches(text=text,mode=mode,synthetic_fixtures_only=True)
                self.assertEqual([b.id for b in batches.items], [str(self.one.pk),str(self.two.pk)])
                self.assertEqual([b.item_count for b in batches.items], [8,8])
        self.assertEqual(self.read(text='%_',mode='literal').total,0)

    def test_missing_refs_and_shared_external_ids_do_not_imply_verification(self):
        data = self.read(batch_id=self.one.pk)
        self.assertEqual(data.items[0].external_id, data.items[3].external_id)
        self.assertNotEqual(data.items[0].id, data.items[3].id)
        detail = services.workflow_item(self.items[1].pk,synthetic_fixtures_only=True)
        self.assertEqual(detail.references,())
        self.assertEqual(detail.item.verified_reference_count,0)
        self.assertEqual(detail.item.review_status,'IN_REVIEW')
        self.assertEqual(data.items[0].intake_status,'READY_FOR_EDITOR')
        self.assertEqual(data.items[0].verified_reference_count,0)
        with self.assertRaises(services.WorkflowItemNotFound):
            services.workflow_item(self.items[0].pk,batch_id=self.two.pk,synthetic_fixtures_only=True)
        self.assertEqual(self.read(batch_id=self.one.pk).items[-1].question_original,None)

    def test_lossless_provenance_numeric_and_invalid_rows(self):
        raw=(' {"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
             '{ "external_id":73.000000000000001,"question":"  سُؤَال\\t\\n  ",'
             '"reference_links":[1e-20000,null,{"x":1e-999999999999999999999999}]},null]} ').encode()
        batch,items=self.persist(raw)
        parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        detail=services.workflow_item(items[0].pk,synthetic_fixtures_only=True)
        self.assertEqual(detail.source, parsed.item_sources[0])
        self.assertEqual(detail.item.question_original,parsed.items[0]['question'])
        self.assertIsNone(detail.item.external_id)
        for row,source in zip(detail.references,parsed.reference_sources[0]):
            self.assertEqual(row.source,source)
            self.assertIsNone(row.citation_text)
            self.assertEqual(row.reference_status,'UNVERIFIED')
        response=views.api_workflow_item(self.request(),str(items[0].pk))
        self.assertEqual(response.status_code,200)
        self.assertIn(b'73.000000000000001',response.content)
        self.assertIn(b'1e-20000',response.content)
        self.assertIn(b'1e-999999999999999999999999',response.content)
        missing=services.workflow_item(items[1].pk,synthetic_fixtures_only=True)
        self.assertEqual(missing.source.text,'null')

    def test_verified_citation_is_only_persisted_verified_reference(self):
        f.seed_reference_catalog(synthetic_fixtures_only=True)  # separate guarded unit, no outer atomic
        ref=IntakeReference.objects.get(intake_item=self.items[0])
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            ref.reference_status='VERIFIED';ref.verified_identity=dict(c.VERIFIED_IDENTITIES[0])
            ref.citation_text='عنوان اصطناعي <أصل>؛ ليس فتوى';ref.save()
        detail=services.workflow_item(self.items[0].pk,synthetic_fixtures_only=True)
        self.assertEqual(detail.item.verified_reference_count,1)
        self.assertEqual(detail.references[0].citation_text,ref.citation_text)
        self.assertEqual(detail.references[0].source.text,ref.original_pointer)
        unmatched=IntakeReference.objects.get(intake_item=self.items[6])
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            unmatched.reference_status='MISMATCHED';unmatched.save()
        mismatch=services.workflow_item(self.items[6].pk,synthetic_fixtures_only=True).references[0]
        self.assertEqual(mismatch.reference_status,'MISMATCHED')
        self.assertIsNone(mismatch.citation_text)

    def test_api_and_ssr_context_share_filters_page_originals_and_errors(self):
        for mode,text in [('exact','سؤال اصطناعي'),('literal','سؤال اصطناعي'),('normalized','سُؤَال اصطناعي'),('normalized','')]:
            request=self.request(batch=str(self.one.pk),q=text,mode=mode,limit='1',offset='0')
            api=views.api_workflow_items(request)
            self.assertEqual(api.status_code,200)
            payload=json.loads(api.content)
            context=views.workflow_read_context(request)
            self.assertEqual([r['id'] for r in payload['items']],[r.id for r in context['workflow_page'].items])
            self.assertEqual(context['workflow_query'],text)
            self.assertEqual(context['workflow_page'].total,payload['total'])
        self.assertEqual(views.api_workflow_items(self.request(batch=str(uuid4()))).status_code,404)
        self.assertEqual(views.api_workflow_item(self.request(),str(uuid4())).status_code,404)

    def test_reads_are_select_only_bounded_and_measure_queries(self):
        before=[model.objects.count() for model in (IntakeBatch,IntakeItem,IntakeReference)]
        stats={}
        for mode in ['literal','normalized']:
            start=perf_counter()
            with CaptureQueriesContext(connection) as capture:
                page=self.read(batch_id=self.one.pk,text='سؤال',mode=mode,page=Page(2))
            statements=[q['sql'].lstrip().upper() for q in capture]
            self.assertTrue(all(sql.startswith(('SELECT','DECLARE','FETCH','CLOSE')) for sql in statements),statements)
            self.assertLessEqual(len(statements),10)
            self.assertLessEqual(len(page.items),2)
            stats[mode]={'queries':len(capture),'wall_ms':round((perf_counter()-start)*1000,3)}
        self.assertEqual(before,[model.objects.count() for model in (IntakeBatch,IntakeItem,IntakeReference)])
        print('WAVE7_E4_READ_MEASUREMENTS='+json.dumps(stats,sort_keys=True))

    def test_limits_fail_closed_and_guards_survive_reconfiguration(self):
        with patch.object(services,'WORKFLOW_MAX_SEARCH_ROWS',1):
            with self.assertRaises(services.WorkflowSearchScopeRequired): self.read(text='سؤال')
        with patch.object(services,'WORKFLOW_MAX_SEARCH_BYTES',1):
            with self.assertRaises(services.WorkflowSearchScopeRequired): self.read(batch_id=self.one.pk,text='سؤال')
        with patch.dict(os.environ,{'FATWA_WAVE7_SYNTHETIC_READS':'0'}):
            with self.assertRaises(services.WorkflowReadsDisabled): self.read()
        with patch.dict(os.environ,{'FATWA_WAVE7_SYNTHETIC_WRITES':'0'}):
            with self.assertRaises(services.WorkflowReadUnavailable): self.read()
        with self.assertRaises(InvalidQuery): services.workflow_items(synthetic_fixtures_only=False)
        with self.assertRaises(services.WorkflowReadUnavailable): services.workflow_items(synthetic_fixtures_only=True,using='other')

    def test_summaries_never_materialize_original_payload_or_source_tokens(self):
        for label, operation in [('items', lambda: self.read(page=Page(1))),
                                 ('batches', lambda: services.workflow_batches(page=Page(1),synthetic_fixtures_only=True))]:
            with self.subTest(label=label), CaptureQueriesContext(connection) as queries:
                result=operation()
                self.assertEqual(len(result.items),1)
                page_sql=queries[-1]['sql']
                for source_field in ['original_payload','payload_snapshot','original_row','original_pointer']:
                    self.assertNotIn('"'+source_field+'"',page_sql)

    @override_settings(ROOT_URLCONF='tests.integration.api.test_wave7_workflow_reads')
    def test_real_get_head_batch_api_and_detail_return_state(self):
        from urllib.parse import parse_qs
        self.client.defaults['HTTP_HOST']='127.0.0.1'
        params={'batch':str(self.one.pk),'q':'  سؤال  ','mode':'literal',
                'intake_status':'NEEDS_REVIEW','review_status':'UNREVIEWED','limit':'1','offset':'1'}
        request=self.request(**params)
        listing=views.workflow_read_context(request)
        detail=views.workflow_read_context(request,item_id=self.items[4].pk)
        self.assertEqual(detail['workflow_item'].item.id,str(self.items[4].pk))
        self.assertEqual(parse_qs(detail['workflow_return_query']),{k:[v] for k,v in params.items()})
        self.assertEqual(listing['workflow_filter_query'],detail['workflow_return_query'])
        api=self.client.get('/dev/wave7/api/items',params)
        self.assertEqual(api.status_code,200)
        self.assertEqual([row['id'] for row in api.json()['items']],
                         [row.id for row in listing['workflow_page'].items])
        head=self.client.head('/dev/wave7/api/items',params)
        self.assertEqual((head.status_code,head.content),(200,b''))
        self.assertEqual(head['Content-Type'],api['Content-Type'])
        self.assertEqual(head['Cache-Control'],'no-store')
        batches=self.client.get('/dev/wave7/api/batches',{'limit':'1','offset':'1'})
        self.assertEqual(batches.status_code,200)
        self.assertEqual([row['id'] for row in batches.json()['items']],[str(self.two.pk)])
        self.assertEqual(batches.json()['total'],2)
        html=__import__('django.template',fromlist=['Template','Context'])
        rendered=html.Template('{{ workflow_item.item.question_original }}').render(html.Context(detail))
        self.assertIn('سؤال محفوظ',rendered)
