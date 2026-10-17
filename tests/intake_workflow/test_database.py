"""Real PG17/18 E1 services. Never collect this module in the port-1 pure runner."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
from threading import Barrier, local
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.db.models.query import QuerySet
from django.test import TransactionTestCase

from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow import intake as service
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
from .test_check import payload, valid_row


class IntakeDatabaseTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context = g.require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != settings.WAVE7_TEST_DATABASE_NAME:
            raise RuntimeError('E1 tests require the task-owned test database')
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int")
            name, role, version = cursor.fetchone()
        if name != context.database_name or role != c.DATABASE_ROLE or version // 10000 not in (17,18):
            raise RuntimeError('E1 test database identity mismatch')
        print('E1_ACTUAL_DATABASE='+json.dumps(dict(database=name, role=role, postgres=version)))

    def ingest(self, raw=None, key='E1-key'):
        return service.import_intake(raw if raw is not None else f.synthetic_payload(),
                                     idempotency_key=key, synthetic_fixtures_only=True)

    def counts(self):
        return [model.objects.count() for model in (IntakeBatch, IntakeItem, IntakeReference, ReviewEvent)]

    def test_persists_all_fixture_rows_exactly_with_unverified_references(self):
        raw = f.synthetic_payload()
        checked = service.check_intake(raw, synthetic_fixtures_only=True)
        result = self.ingest(raw)
        self.assertEqual(result.decision, 'CREATE')
        batch = IntakeBatch.objects.get(pk=result.batch_id)
        self.assertEqual(bytes(batch.original_payload), raw)
        self.assertEqual(batch.payload_snapshot, raw.decode())
        self.assertEqual(batch.payload_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual((batch.scope,batch.source_config_id), (c.SYNTHETIC_SCOPE,c.SOURCE_CONFIG_ID))
        items = list(batch.items.all())
        self.assertEqual(len(items), 8)
        for item, checked_item in zip(items, checked.items, strict=True):
            self.assertEqual(item.original_row, checked_item.source.text)
            self.assertEqual(raw[item.source_byte_start:item.source_byte_end], item.original_row.encode())
            self.assertEqual(item.question_original, checked_item.question_original)
            self.assertEqual(item.external_id, checked_item.external_id)
            self.assertEqual(item.intake_status, checked_item.intake_status)
            self.assertEqual(item.review_status, 'UNREVIEWED')
        self.assertEqual(items[0].question_original, f.ORIGINAL_QUESTION)
        self.assertEqual(items[0].external_id, items[3].external_id)
        self.assertEqual(items[-1].original_row, 'null')
        self.assertEqual(items[6].intake_status, 'READY_FOR_EDITOR')
        for ref in IntakeReference.objects.order_by('intake_item__row_ordinal','reference_ordinal'):
            self.assertEqual((ref.reference_status,ref.verified_identity,ref.citation_text),('UNVERIFIED',{},''))
            self.assertEqual(raw[ref.source_byte_start:ref.source_byte_end],ref.original_pointer.encode())
        self.assertEqual(result.item_count,8)
        self.assertEqual(result.reference_count,3)
        self.assertEqual(ReviewEvent.objects.count(),0)

    def test_same_raw_replay_and_changed_raw_409_without_mutation(self):
        first = self.ingest()
        before = list(IntakeItem.objects.values())
        replay = self.ingest()
        self.assertEqual(replay.decision,'REPLAY')
        self.assertEqual((first.batch_id,first.payload_sha256),(replay.batch_id,replay.payload_sha256))
        with self.assertRaises(c.IdempotencyConflict) as caught:
            self.ingest(b' '+f.synthetic_payload())
        self.assertEqual((caught.exception.code,caught.exception.status_code),('IDEMPOTENCY_CONFLICT',409))
        self.assertEqual(self.counts(),[1,8,3,0])
        self.assertEqual(list(IntakeItem.objects.values()),before)

    def test_same_raw_different_keys_are_distinct_batches(self):
        one,two = self.ingest(key='one'),self.ingest(key='two')
        self.assertNotEqual(one.batch_id,two.batch_id)
        self.assertEqual(self.counts(),[2,16,6,0])

    def test_numbers_and_malformed_references_preserve_exact_tokens_and_offsets(self):
        raw=(b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
             b'{ "external_id":73.000000000000001,"question":"  Q\\t\\n ",'
             b'"reference_links":[ {"source_id":73.000000000000001},null,1e-20000 ]},'
             +b'9'*6000+b',1e-999999999999999999999999999,null]}')
        result=self.ingest(raw)
        batch=IntakeBatch.objects.get(pk=result.batch_id)
        self.assertEqual(bytes(batch.original_payload),raw)
        items=list(batch.items.all())
        self.assertEqual(len(items),4)
        self.assertTrue(all(i.external_id is None and i.intake_status=='BLOCKED_INVALID' for i in items))
        self.assertEqual(items[0].question_original,'  Q\t\n ')
        for item in items:
            self.assertEqual(raw[item.source_byte_start:item.source_byte_end],item.original_row.encode())
        self.assertEqual([r.original_pointer for r in items[0].references.all()],
                         ['{"source_id":73.000000000000001}','null','1e-20000'])
        self.assertTrue(all(r.citation_text=='' and r.reference_status=='UNVERIFIED'
                            for r in IntakeReference.objects.all()))

    def test_partial_failure_rolls_back_batch_items_references_and_key(self):
        original=QuerySet.bulk_create
        def fail_references(queryset, objects, *args, **kwargs):
            if queryset.model is IntakeReference:
                self.assertEqual(IntakeBatch.objects.count(),1)
                self.assertEqual(IntakeItem.objects.count(),8)
                raise RuntimeError('synthetic reference failure')
            return original(queryset, objects, *args, **kwargs)
        with patch.object(QuerySet,'bulk_create',fail_references),self.assertRaisesRegex(RuntimeError,'synthetic reference failure'):
            self.ingest()
        self.assertEqual(self.counts(),[0,0,0,0])
        self.assertEqual(self.ingest().decision,'CREATE')

    def test_non_key_integrity_error_is_not_misreported_as_replay(self):
        from django.db import IntegrityError
        original=QuerySet.create
        def wrong_hash(queryset,**values):
            if queryset.model is IntakeBatch:
                values['payload_sha256']='c'*64
            return original(queryset,**values)
        with patch.object(QuerySet,'create',wrong_hash),self.assertRaises(IntegrityError):
            self.ingest()
        self.assertEqual(self.counts(),[0,0,0,0])
        self.assertEqual(self.ingest().decision,'CREATE')

    def race(self, raws):
        barrier,state=Barrier(2),local()
        original=service._existing_batch
        def synchronized(*args,**kwargs):
            value=original(*args,**kwargs)
            if not getattr(state,'read',False):
                state.read=True
                self.assertIsNone(value)
                barrier.wait(timeout=20)
            return value
        def attempt(raw):
            try:
                result=self.ingest(raw,key='E1-race')
                return result.decision,result.batch_id
            except c.IdempotencyConflict:
                return 'CONFLICT',None
            finally:
                connections['default'].close()
        with patch.object(service,'_existing_batch',synchronized),ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(attempt,raws))

    def test_same_hash_uniqueness_race_recovers_savepoint_and_replays(self):
        results=self.race([f.synthetic_payload()]*2)
        self.assertCountEqual([r[0] for r in results],['CREATE','REPLAY'])
        self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(self.counts(),[1,8,3,0])
        self.assertEqual(self.ingest(key='after-race').decision,'CREATE')

    def test_different_hash_race_has_one_winner_one_409_and_no_partial_children(self):
        results=self.race([f.synthetic_payload(),b' '+f.synthetic_payload()])
        self.assertCountEqual([r[0] for r in results],['CREATE','CONFLICT'])
        self.assertEqual(self.counts(),[1,8,3,0])

    def test_guard_configuration_refusal_precedes_any_transaction_or_write(self):
        for override in ({'FATWA_WAVE7_SYNTHETIC_WRITES':'0'}, {'FATWA_PRODUCTION':'1'}, {'PGOPTIONS':'untrusted'}):
            with self.subTest(override=override),patch.dict(os.environ,override),patch.object(g.transaction,'atomic') as atomic:
                with self.assertRaises(g.SyntheticWriteDenied):
                    self.ingest()
                atomic.assert_not_called()
        self.assertEqual(self.counts(),[0,0,0,0])

    def test_refuses_caller_transaction_missing_ack_alias_and_invalid_keys(self):
        with transaction.atomic(),self.assertRaises(g.SyntheticWriteDenied):
            self.ingest()
        for options in ({'synthetic_fixtures_only':False},{'using':'other'},
                        {'idempotency_key':'bad key'},{'idempotency_key':73},{'idempotency_key':'x'*129}):
            values=dict(idempotency_key='key',synthetic_fixtures_only=True)|options
            with self.subTest(options=options),self.assertRaises((c.ContractError,g.SyntheticWriteDenied)):
                service.import_intake(f.synthetic_payload(),**values)
        self.assertEqual(self.counts(),[0,0,0,0])

    def test_invalid_envelope_and_bounds_reject_before_guard(self):
        for raw in (b'{}',b'x'*1_000_001,payload([None]*1001),payload([valid_row(reference_links=[None]*101)])):
            with self.subTest(size=len(raw)),patch.object(g,'synthetic_atomic') as atomic,self.assertRaises(c.ContractError):
                self.ingest(raw)
            atomic.assert_not_called()
        self.assertEqual(self.counts(),[0,0,0,0])

    def test_row_and_reference_maxima_persist_without_filtering(self):
        rows=[valid_row(reference_links=[None]*100)]+[None]*999
        result=self.ingest(payload(rows))
        self.assertEqual((result.item_count,result.reference_count),(1000,100))
        self.assertEqual(self.counts(),[1,1000,100,0])

    def test_exact_million_byte_numeric_row_persists_without_numeric_coercion(self):
        prefix=b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
        raw=prefix+b'9'*(1_000_000-len(prefix)-2)+b']}'
        result=self.ingest(raw)
        item=IntakeItem.objects.get(batch_id=result.batch_id)
        batch=IntakeBatch.objects.get(pk=result.batch_id)
        self.assertEqual((result.item_count,result.reference_count),(1,0))
        self.assertEqual((item.external_id,item.question_original,item.intake_status),(None,None,'BLOCKED_INVALID'))
        self.assertEqual(item.original_row.encode(),raw[len(prefix):-2])
        self.assertEqual(raw[item.source_byte_start:item.source_byte_end],item.original_row.encode())
        self.assertEqual(bytes(batch.original_payload),raw)
        self.assertEqual(batch.payload_sha256,hashlib.sha256(raw).hexdigest())

    def test_management_check_never_writes_and_import_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.json'
            source.write_bytes(f.synthetic_payload())
            out=io.StringIO()
            def no_query(*args,**kwargs):
                raise AssertionError('check performed a database query')
            with patch.dict(os.environ,{'FATWA_WAVE7_SYNTHETIC_WRITES':'0'}),connection.execute_wrapper(no_query):
                call_command('wave7_intake','check',str(source),'--synthetic-fixtures-only',stdout=out)
            self.assertEqual(json.loads(out.getvalue())['item_count'],8)
            self.assertEqual(self.counts(),[0,0,0,0])
            reports=[]
            for _ in range(2):
                out=io.StringIO()
                call_command('wave7_intake','import',str(source),'--synthetic-fixtures-only',
                             '--idempotency-key','CLI-key',stdout=out)
                reports.append(json.loads(out.getvalue()))
            self.assertEqual([r['decision'] for r in reports],['CREATE','REPLAY'])
            self.assertEqual(self.counts(),[1,8,3,0])

    def test_source_catalog_is_never_seeded_or_marked_verified_by_intake(self):
        from apps.reference.models import ReferenceHeading
        with patch.object(f,'seed_reference_catalog',side_effect=AssertionError('implicit seed')):
            self.ingest()
        self.assertEqual(ReferenceHeading.objects.count(),0)
        self.assertFalse(IntakeReference.objects.exclude(reference_status='UNVERIFIED').exists())
