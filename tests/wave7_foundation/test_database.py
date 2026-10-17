"""Actual PG17/18 foundation evidence; no intake/review service implementation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from types import SimpleNamespace
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.db import connection, connections, DatabaseError, IntegrityError, transaction
from django.test import TransactionTestCase, Client, override_settings
from psycopg import sql
from django.test.utils import CaptureQueriesContext

from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent


class FoundationDatabaseTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context=g.require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != settings.WAVE7_TEST_DATABASE_NAME:
            raise RuntimeError('Foundation tests refuse the base/non-test database')
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int")
            name,role,version=cursor.fetchone()
        if name!=context.database_name or role!=c.DATABASE_ROLE or version//10000 not in (17,18):
            raise RuntimeError('Actual foundation test database identity mismatch')
        import subprocess
        sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        dirty=bool(subprocess.check_output(['git','status','--porcelain'],text=True))
        print('WAVE7_TEST_IDENTITY='+json.dumps(dict(sha=sha,working_tree='DIRTY' if dirty else 'CLEAN',
              database=name,role=role,postgres=version,scope=context.scope)))

    def batch(self, key=None):
        raw=f.synthetic_payload()
        return IntakeBatch.objects.create(idempotency_key=key or uuid4().hex,
            original_payload=raw, payload_sha256=hashlib.sha256(raw).hexdigest())

    def item(self, batch, ordinal=1, **changes):
        row=json.loads(batch.original_payload)['items'][ordinal-1]
        return IntakeItem.objects.create(batch=batch,row_ordinal=ordinal,
            external_id=c.valid_external_id(row.get('external_id')) if isinstance(row,dict) else None,
            question_original=row.get('question') if isinstance(row,dict) and isinstance(row.get('question'),str) else None,
            original_row=row,**changes)

    def test_original_bytes_questions_duplicates_and_blocked_rows_persist(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch()
            items=[self.item(batch,n,intake_status='READY_FOR_EDITOR' if n==7 else 'BLOCKED_INVALID') for n in range(1,9)]
        batch.refresh_from_db();items[0].refresh_from_db();items[3].refresh_from_db();items[7].refresh_from_db()
        self.assertEqual(bytes(batch.original_payload),f.synthetic_payload())
        self.assertEqual(batch.payload_snapshot,json.loads(f.synthetic_payload()))
        self.assertEqual(items[0].question_original,f.ORIGINAL_QUESTION)
        self.assertEqual(items[0].external_id,items[3].external_id)
        self.assertIsNone(items[7].original_row)
        self.assertEqual(IntakeItem.objects.filter(batch=batch).count(),8)

    def test_unique_key_same_payload_replay_and_conflict_contract(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            first=self.batch('same-key')
        with self.assertRaises(IntegrityError),g.synthetic_atomic(synthetic_fixtures_only=True):
            self.batch('same-key')
        found=IntakeBatch.objects.get(scope=c.SYNTHETIC_SCOPE,idempotency_key='same-key')
        self.assertEqual(c.idempotency_decision(found.payload_sha256,first.payload_sha256),'REPLAY')
        with self.assertRaises(c.IdempotencyConflict):
            c.idempotency_decision(found.payload_sha256,'c'*64)
        self.assertEqual(IntakeBatch.objects.count(),1)

    def test_all_partial_rows_and_events_roll_back(self):
        with self.assertRaisesRegex(RuntimeError,'synthetic failure'):
            with g.synthetic_atomic(synthetic_fixtures_only=True):
                batch=self.batch();item=self.item(batch)
                ReviewEvent.objects.create(intake_item=item,from_status='UNREVIEWED',to_status='IN_REVIEW',
                    action='start_review',reason='Synthetic rollback probe',operation_id=uuid4())
                raise RuntimeError('synthetic failure')
        self.assertEqual([m.objects.count() for m in (IntakeBatch,IntakeItem,IntakeReference,ReviewEvent)],[0,0,0,0])

    def test_concurrent_unique_insert_has_one_winner_and_no_partial_child(self):
        barrier=Barrier(2)
        def attempt():
            try:
                with g.synthetic_atomic(synthetic_fixtures_only=True):
                    barrier.wait(timeout=10)
                    batch=self.batch('race-key');self.item(batch)
                return 'created'
            except IntegrityError:
                return 'conflict'
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _:attempt(),range(2)))
        self.assertCountEqual(outcomes,['created','conflict'])
        self.assertEqual(IntakeBatch.objects.count(),1)
        self.assertEqual(IntakeItem.objects.count(),1)

    def test_row_and_per_item_reference_ordinals_and_evidence_constraints(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();one=self.item(batch,1);duplicate=self.item(batch,4)
            pointer=one.original_row['reference_links'][0]
            IntakeReference.objects.create(intake_item=one,reference_ordinal=1,original_pointer=pointer)
            IntakeReference.objects.create(intake_item=duplicate,reference_ordinal=1,original_pointer=pointer)
        for action in (lambda:self.item(batch,1),lambda:self.item(batch,0),lambda:IntakeItem.objects.create(batch=batch,row_ordinal=1001,original_row=None),
                       lambda:IntakeReference.objects.create(intake_item=one,reference_ordinal=1,original_pointer=pointer),
                       lambda:IntakeReference.objects.create(intake_item=one,reference_ordinal=101,original_pointer=pointer)):
            with self.subTest(action=action),self.assertRaises((IntegrityError,IndexError)),g.synthetic_atomic(synthetic_fixtures_only=True):
                action()
        self.assertEqual(IntakeReference.objects.count(),2)

    def test_unverified_or_incomplete_identity_cannot_hold_citation(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();item=self.item(batch)
        pointer=item.original_row['reference_links'][0]
        for values in ({'reference_status':'UNVERIFIED','citation_text':'false citation'},
                       {'reference_status':'MISMATCHED','verified_identity':dict(c.VERIFIED_IDENTITIES[0])},
                       {'reference_status':'VERIFIED','verified_identity':{}},
                       {'reference_status':'VERIFIED','verified_identity':dict(c.VERIFIED_IDENTITIES[1])},
                       {'reference_status':'VERIFIED','verified_identity':dict(c.VERIFIED_IDENTITIES[0],source_input_sha256='c'*64)}):
            with self.subTest(values=values),self.assertRaises(IntegrityError),g.synthetic_atomic(synthetic_fixtures_only=True):
                IntakeReference.objects.create(intake_item=item,reference_ordinal=1,original_pointer=pointer,**values)
        f.seed_reference_catalog(synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            ref=IntakeReference.objects.create(intake_item=item,reference_ordinal=1,original_pointer=pointer,
                reference_status='VERIFIED',verified_identity=dict(c.VERIFIED_IDENTITIES[0]),citation_text='عنوان اصطناعي؛ ليس فتوى')
        self.assertEqual(ref.reference_status,'VERIFIED')

    def test_originals_and_scope_and_event_rows_are_immutable(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();item=self.item(batch)
            ref=IntakeReference.objects.create(intake_item=item,reference_ordinal=1,
                original_pointer=item.original_row['reference_links'][0])
            event=ReviewEvent.objects.create(intake_item=item,from_status='UNREVIEWED',to_status='IN_REVIEW',
                action='start_review',reason='Synthetic review start',operation_id=uuid4())
        actions=[lambda:IntakeBatch.objects.filter(pk=batch.pk).update(idempotency_key='rewritten'),
                 lambda:IntakeItem.objects.filter(pk=item.pk).update(question_original='rewritten'),
                 lambda:IntakeReference.objects.filter(pk=ref.pk).update(original_pointer={}),
                 lambda:ReviewEvent.objects.filter(pk=event.pk).update(reason='rewritten'),
                 lambda:ReviewEvent.objects.filter(pk=event.pk).delete()]
        for action in actions:
            with self.subTest(action=action),self.assertRaises(IntegrityError),g.synthetic_atomic(synthetic_fixtures_only=True):
                action()

    def test_snapshot_and_pointer_cannot_be_fabricated(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();item=self.item(batch)
        for model, values in [(IntakeItem,dict(batch=batch,row_ordinal=2,original_row={'fake':True})),
            (IntakeReference,dict(intake_item=item,reference_ordinal=1,original_pointer={'fake':True}))]:
            with self.subTest(model=model),self.assertRaises(IntegrityError),g.synthetic_atomic(synthetic_fixtures_only=True):
                model.objects.create(**values)

    def test_unguarded_dml_and_post_transaction_permit_reuse_fail(self):
        with self.assertRaises(IntegrityError):
            self.batch()
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch()
        with self.assertRaises(IntegrityError):
            self.item(batch)
        with self.assertRaises(g.SyntheticWriteDenied),transaction.atomic():
            g.require_synthetic_write(synthetic_fixtures_only=True)

    def test_missing_enablement_or_ack_has_no_write_or_transaction(self):
        for env,ack in [({'FATWA_WAVE7_SYNTHETIC_WRITES':'0'},True),({'FATWA_PRODUCTION':''},True),({},False)]:
            with self.subTest(env=env,ack=ack),patch.dict(os.environ,env),patch.object(g.transaction,'atomic') as atomic:
                with self.assertRaises(g.SyntheticWriteDenied):
                    with g.synthetic_atomic(synthetic_fixtures_only=ack):
                        self.fail('entered write body')
                atomic.assert_not_called()
        self.assertEqual(IntakeBatch.objects.count(),0)

    def test_owned_nonempty_database_remains_usable_and_marker_is_immutable(self):
        before=g.require_synthetic_write(synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            self.batch()
        self.assertEqual(g.initialize_synthetic_database(synthetic_fixtures_only=True),before)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            self.batch()
        self.assertEqual(IntakeBatch.objects.count(),2)
        with self.assertRaises(IntegrityError),transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE wave7_synthetic_ownership SET scope='wrong'")

    def test_review_operation_unique_and_transition_constraints(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();item=self.item(batch);operation=uuid4()
            ReviewEvent.objects.create(intake_item=item,operation_id=operation,from_status='UNREVIEWED',
                to_status='IN_REVIEW',action='start_review',reason='Synthetic start')
        for values in (dict(operation_id=operation,from_status='UNREVIEWED',to_status='IN_REVIEW',action='start_review'),
                       dict(operation_id=uuid4(),from_status='UNREVIEWED',to_status='REVIEWED_INTERNAL',action='complete_review')):
            with self.subTest(values=values),self.assertRaises(IntegrityError),g.synthetic_atomic(synthetic_fixtures_only=True):
                ReviewEvent.objects.create(intake_item=item,reason='Synthetic invalid retry',**values)

    def test_http_unsafe_methods_still_fail_before_database_queries(self):
        client=Client(HTTP_HOST='127.0.0.1')
        for method in ('post','put','patch','delete'):
            with self.subTest(method=method),CaptureQueriesContext(connection) as queries:
                response=getattr(client,method)('/dev/editorial-preview/pipeline',data='{}',content_type='application/json')
            self.assertEqual(response.status_code,405)
            self.assertEqual(len(queries),0)


    @contextmanager
    def probe(self):
        g.require_synthetic_write(synthetic_fixtures_only=True)
        name='wave7_synthetic_probe_'+uuid4().hex[:12]
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        config=copy.deepcopy(connection.settings_dict)
        config['NAME']=name;config['TEST']['NAME']='test_'+name
        probe=type(connections['default'])(config,alias='wave7_probe')
        try:
            with patch.object(g,'settings',SimpleNamespace(DATABASES={'default':config},
                    WAVE7_BASE_DATABASE_NAME=name,WAVE7_TEST_DATABASE_NAME='test_'+name,
                    WAVE7_SCOPE=c.SYNTHETIC_SCOPE,WAVE7_SOURCE_CONFIG_ID=c.SOURCE_CONFIG_ID)),\
                    patch.object(g,'_connection',return_value=probe):
                yield probe
        finally:
            probe.close()
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def test_unknown_nonempty_database_rejects_before_atomic_and_is_not_reset(self):
        with self.probe() as probe:
            with probe.cursor() as cursor:
                cursor.execute('CREATE TABLE unknown_existing (value integer)')
                cursor.execute('INSERT INTO unknown_existing VALUES (73)')
            with patch.object(g.transaction,'atomic') as atomic:
                with self.assertRaises(g.SyntheticWriteDenied) as caught:
                    g.initialize_synthetic_database(synthetic_fixtures_only=True)
                self.assertEqual(caught.exception.code,'UNKNOWN_NONEMPTY_DATABASE')
                atomic.assert_not_called()
            with probe.cursor() as cursor:
                cursor.execute('SELECT value FROM unknown_existing')
                self.assertEqual(cursor.fetchall(),[(73,)])
                cursor.execute("SELECT to_regclass('public.wave7_synthetic_ownership')")
                self.assertIsNone(cursor.fetchone()[0])

    def test_empty_unclaimed_database_has_no_write_permission(self):
        with self.probe() as probe,patch.object(g.transaction,'atomic') as atomic:
            with self.assertRaises(g.SyntheticWriteDenied):
                with g.synthetic_atomic(synthetic_fixtures_only=True):
                    self.fail('unknown database entered write body')
            atomic.assert_not_called()
            with probe.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
                self.assertEqual(cursor.fetchone()[0],0)

    def test_batch_hash_fixed_scope_and_payload_shape_constraints(self):
        raw=f.synthetic_payload()
        cases=[{'scope':'caller-scope'},{'source_config_id':'caller-config'},
               {'contract_version':'other-version'},{'payload_sha256':'c'*64},
               {'idempotency_key':'bad key'},
               {'original_payload':b'x'*1000001,'payload_sha256':hashlib.sha256(b'x'*1000001).hexdigest()}]
        for invalid in [b'{}', b'[]', json.dumps(dict(json.loads(raw),synthetic_fixtures_only=False)).encode(),
                        json.dumps(dict(json.loads(raw),scope='untrusted')).encode()]:
            cases.append({'original_payload':invalid,'payload_sha256':hashlib.sha256(invalid).hexdigest()})
        for changes in cases:
            values=dict(idempotency_key=uuid4().hex,original_payload=raw,payload_sha256=hashlib.sha256(raw).hexdigest())|changes
            with self.subTest(changes=list(changes)),self.assertRaises(DatabaseError),g.synthetic_atomic(synthetic_fixtures_only=True):
                IntakeBatch.objects.create(**values)

    def test_fixed_reference_fixture_is_guarded_idempotent_and_exact(self):
        with self.assertRaises(g.SyntheticWriteDenied):
            f.seed_reference_catalog()
        self.assertEqual(f.seed_reference_catalog(synthetic_fixtures_only=True),7001)
        self.assertEqual(f.seed_reference_catalog(synthetic_fixtures_only=True),7001)
        from apps.reference.models import ReferenceHeading
        self.assertEqual(ReferenceHeading.objects.filter(edition_id=7001).count(),3)


    def test_ready_intake_can_remain_unverified_without_citation(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();item=self.item(batch,7,intake_status='READY_FOR_EDITOR')
            ref=IntakeReference.objects.create(intake_item=item,reference_ordinal=1,
                original_pointer=item.original_row['reference_links'][0])
        self.assertEqual((item.intake_status,item.review_status,ref.reference_status,ref.citation_text),
                         ('READY_FOR_EDITOR','UNREVIEWED','UNVERIFIED',''))

    def test_verified_identity_requires_actual_matching_catalog_rows(self):
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch();item=self.item(batch)
        with self.assertRaises(IntegrityError),g.synthetic_atomic(synthetic_fixtures_only=True):
            IntakeReference.objects.create(intake_item=item,reference_ordinal=1,
                original_pointer=item.original_row['reference_links'][0],reference_status='VERIFIED',
                verified_identity=dict(c.VERIFIED_IDENTITIES[0]),citation_text='No absent catalog proof')
        self.assertEqual(IntakeReference.objects.count(),0)

    def test_unknown_database_migrate_command_rejects_before_schema_creation(self):
        import subprocess
        import sys
        from pathlib import Path
        with self.probe() as probe:
            with probe.cursor() as cursor:
                cursor.execute('CREATE TABLE unknown_fixture (value integer)')
                cursor.execute('INSERT INTO unknown_fixture VALUES (73)')
            env=dict(os.environ,PGDATABASE=probe.settings_dict['NAME'],
                     PGTESTDATABASE=probe.settings_dict['TEST']['NAME'])
            result=subprocess.run([sys.executable,'manage.py','migrate','--noinput','--settings=config.settings.wave7_test'],
                cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,timeout=30)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'DATABASE_OWNERSHIP_REQUIRED',result.stderr)
            with probe.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.django_migrations')")
                self.assertIsNone(cursor.fetchone()[0])
                cursor.execute('SELECT value FROM unknown_fixture')
                self.assertEqual(cursor.fetchall(),[(73,)])

    def test_foreign_ownership_marker_rejects_without_reinitialization(self):
        with self.probe() as probe:
            with probe.cursor() as cursor:
                cursor.execute('CREATE TABLE wave7_synthetic_ownership ('
                    'scope text,source_config_id text,contract_version text,database_name text,database_oid bigint)')
                cursor.execute("INSERT INTO wave7_synthetic_ownership VALUES ('unknown-owner','other','other',current_database(),0)")
            with patch.object(g.transaction,'atomic') as atomic:
                with self.assertRaises(g.SyntheticWriteDenied):
                    g.initialize_synthetic_database(synthetic_fixtures_only=True)
                atomic.assert_not_called()
            with probe.cursor() as cursor:
                cursor.execute('SELECT scope FROM wave7_synthetic_ownership')
                self.assertEqual(cursor.fetchall(),[('unknown-owner',)])
