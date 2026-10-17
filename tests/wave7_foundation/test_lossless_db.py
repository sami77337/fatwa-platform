"""Actual PG17/18 closure of approved lossless text/byte-offset storage."""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from django.db import connection, DatabaseError, transaction
from django.test import TransactionTestCase

from apps.intake_workflow import contracts as c, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference
from apps.intake_workflow import fixtures as f
from . import test_database as foundation


class LosslessDatabaseTests(TransactionTestCase):
    probe = foundation.FoundationDatabaseTests.probe
    def batch(self, raw):
        return IntakeBatch.objects.create(idempotency_key=uuid4().hex,original_payload=raw,
            payload_sha256=hashlib.sha256(raw).hexdigest())

    def item_values(self, batch, parsed, ordinal=1):
        row,source = parsed.items[ordinal-1],parsed.item_sources[ordinal-1]
        return dict(batch=batch,row_ordinal=ordinal,original_row=source.text,
            source_byte_start=source.start,source_byte_end=source.end,
            external_id=c.valid_external_id(row.get('external_id')) if isinstance(row,dict) else None,
            question_original=row.get('question') if isinstance(row,dict) and isinstance(row.get('question'),str) else None,
            intake_status='BLOCKED_INVALID',validation_results={'errors':['invalid_synthetic_row']})

    def reference_values(self, item, parsed, ordinal=1):
        source = parsed.reference_sources[item.row_ordinal-1][ordinal-1]
        return dict(intake_item=item,reference_ordinal=ordinal,original_pointer=source.text,
                    source_byte_start=source.start,source_byte_end=source.end)

    def test_one_million_byte_integer_source_is_stored_exactly(self):
        prefix=b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
        digits=b'9'*(c.MAX_INPUT_BYTES-len(prefix)-2)
        raw=prefix+digits+b']}'
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch(raw)
            item=IntakeItem.objects.create(batch=batch,row_ordinal=1,original_row=digits.decode(),
                source_byte_start=len(prefix),source_byte_end=len(raw)-2,external_id=None,
                intake_status='BLOCKED_INVALID',validation_results={'errors':['invalid_synthetic_row']})
        batch.refresh_from_db();item.refresh_from_db()
        self.assertEqual(bytes(batch.original_payload),raw)
        self.assertEqual(batch.payload_snapshot.encode(),raw)
        self.assertEqual(batch.payload_sha256,hashlib.sha256(raw).hexdigest())
        self.assertEqual(item.original_row.encode(),digits)
        self.assertEqual(raw[item.source_byte_start:item.source_byte_end],digits)
        self.assertIsNone(item.external_id)

    def test_numeric_rows_and_references_keep_raw_sha_text_offsets_without_rollback(self):
        self.assertEqual(IntakeBatch._meta.get_field('payload_snapshot').get_internal_type(),'TextField')
        digits = b'9'*6000
        raw = (' \n{"schema":"fatwa.wave7.synthetic-intake.v1", "synthetic_fixtures_only":true, "items":['
               '{ "external_id":73.000000000000001,"question":"  سُؤَال\\t\\n  ",'
               '"reference_links":[ {"unknown":1e-20000},1e-20000,null ]},').encode()+digits+b',1e-999999999999999999999999]}\t'
        parsed = c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = self.batch(raw)
            items = [IntakeItem.objects.create(**self.item_values(batch,parsed,n)) for n in (1,2,3)]
            refs = [IntakeReference.objects.create(**self.reference_values(items[0],parsed,n)) for n in (1,2,3)]
        batch.refresh_from_db()
        self.assertEqual(bytes(batch.original_payload),raw)
        self.assertEqual(batch.payload_sha256,hashlib.sha256(raw).hexdigest())
        self.assertEqual(batch.payload_snapshot,raw.decode('utf-8'))
        self.assertEqual(parsed.items[0]['external_id'],Decimal('73.000000000000001'))
        self.assertIs(type(parsed.items[1]),int)
        for item,source in zip(items,parsed.item_sources):
            item.refresh_from_db()
            self.assertEqual(item.original_row,source.text)
            self.assertEqual((item.source_byte_start,item.source_byte_end),(source.start,source.end))
            self.assertEqual(raw[item.source_byte_start:item.source_byte_end],item.original_row.encode())
            self.assertIsNone(item.external_id)
            self.assertEqual(item.validation_results,{'errors':['invalid_synthetic_row']})
        for ref,source in zip(refs,parsed.reference_sources[0]):
            ref.refresh_from_db()
            self.assertEqual(ref.original_pointer,source.text)
            self.assertEqual(raw[ref.source_byte_start:ref.source_byte_end],ref.original_pointer.encode())
            self.assertGreaterEqual(ref.source_byte_start,items[0].source_byte_start)
            self.assertLessEqual(ref.source_byte_end,items[0].source_byte_end)
            self.assertEqual((ref.reference_status,ref.verified_identity,ref.citation_text),('UNVERIFIED',{},''))
        self.assertEqual((IntakeItem.objects.count(),IntakeReference.objects.count()),(3,3))

    def test_tampered_row_text_offsets_ordinal_and_utf8_boundaries_are_rejected(self):
        row = '{ "question":"أصل", "external_id":73.000000000000001 }'
        raw = ('{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
               '"items":['+row+','+row+']}').encode()
        parsed = c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = self.batch(raw)
        values = self.item_values(batch,parsed)
        second = parsed.item_sources[1]
        cases = [dict(original_row=row.replace('73.000000000000001','73.0')),
                 dict(original_row=row.replace(' ','')),dict(source_byte_start=-1),
                 dict(source_byte_end=len(raw)+1),dict(source_byte_start=values['source_byte_start']+1),
                 dict(source_byte_start=second.start,source_byte_end=second.end),
                 dict(source_byte_end=values['source_byte_start']),dict(original_row=None)]
        for changes in cases:
            with self.subTest(changes=changes),g.synthetic_atomic(synthetic_fixtures_only=True):
                with self.assertRaises(DatabaseError),transaction.atomic():
                    IntakeItem.objects.create(**(values|changes))
        self.assertEqual(IntakeItem.objects.count(),0)

    def test_pointer_offset_must_be_the_exact_reference_not_a_matching_shadow_or_sibling(self):
        pointer = '{ "unknown":1e-20000 }'
        row = '{"shadow":['+pointer+'],"reference_links":['+pointer+','+pointer+']}'
        raw = ('{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
               '"items":['+row+','+row+']}').encode()
        parsed = c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = self.batch(raw)
            item = IntakeItem.objects.create(**self.item_values(batch,parsed))
        values = self.reference_values(item,parsed)
        shadow = raw.index(pointer.encode())
        next_ref,other_row = parsed.reference_sources[0][1],parsed.reference_sources[1][0]
        cases = [dict(original_pointer=pointer.replace('1e-20000','0')),
                 dict(source_byte_start=shadow,source_byte_end=shadow+len(pointer.encode())),
                 dict(source_byte_start=next_ref.start,source_byte_end=next_ref.end),
                 dict(source_byte_start=other_row.start,source_byte_end=other_row.end),
                 dict(source_byte_end=len(raw)+1),dict(source_byte_start=-1)]
        for changes in cases:
            with self.subTest(changes=changes),g.synthetic_atomic(synthetic_fixtures_only=True):
                with self.assertRaises(DatabaseError),transaction.atomic():
                    IntakeReference.objects.create(**(values|changes))
        self.assertEqual(IntakeReference.objects.count(),0)

    def test_storage_invalid_unicode_and_duplicate_keys_still_leave_no_batch(self):
        prefix = b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
        cases = [prefix+b'{"question":"a","question":"b"}]}',prefix+b'"\\u0000"]}',
                 prefix+b'"\\ud800"]}',prefix+b'"\\udc00"]}',prefix+b'{"\\ud800":0}]}',
                 prefix+b'NaN]}',prefix+b'Infinity]}']
        for raw in cases:
            with self.subTest(raw=raw),g.synthetic_atomic(synthetic_fixtures_only=True):
                with self.assertRaises(DatabaseError),transaction.atomic():
                    self.batch(raw)
        self.assertEqual(IntakeBatch.objects.count(),0)

    def test_deep_valid_rows_and_literal_escape_text_have_no_new_storage_restriction(self):
        nested=b'['*600+b'1e-20000'+b']'*600
        raw=(b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
             b'"items":['+nested+b',{"question":"literal \\\\u0000 and \\\"quote\\\""}]}')
        parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch(raw)
            first=IntakeItem.objects.create(**self.item_values(batch,parsed))
            second=IntakeItem.objects.create(**self.item_values(batch,parsed,2))
        self.assertEqual(first.original_row,nested.decode())
        self.assertEqual(second.question_original,'literal \\u0000 and "quote"')

    def test_source_offsets_and_text_are_immutable_while_derived_state_can_change(self):
        raw=f.synthetic_payload()
        parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch(raw)
            item=IntakeItem.objects.create(**self.item_values(batch,parsed))
            ref=IntakeReference.objects.create(**self.reference_values(item,parsed))
        actions=[lambda:IntakeBatch.objects.filter(pk=batch.pk).update(payload_snapshot='{}'),
                 lambda:IntakeItem.objects.filter(pk=item.pk).update(source_byte_start=item.source_byte_start+1),
                 lambda:IntakeItem.objects.filter(pk=item.pk).update(source_byte_end=item.source_byte_end-1),
                 lambda:IntakeReference.objects.filter(pk=ref.pk).update(source_byte_start=ref.source_byte_start+1),
                 lambda:IntakeReference.objects.filter(pk=ref.pk).update(source_byte_end=ref.source_byte_end-1)]
        for action in actions:
            with self.subTest(action=action),g.synthetic_atomic(synthetic_fixtures_only=True):
                with self.assertRaises(DatabaseError),transaction.atomic():
                    action()
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            IntakeItem.objects.filter(pk=item.pk).update(intake_status='NEEDS_REVIEW')
        item.refresh_from_db()
        self.assertEqual(item.intake_status,'NEEDS_REVIEW')
        self.assertEqual(item.original_row,parsed.item_sources[0].text)

    def test_six_field_c2_identity_is_checked_without_rewriting_original_pointer(self):
        identity=dict(c.VERIFIED_IDENTITIES[0])
        pointer={key:value for key,value in identity.items() if key not in ('edition_id','source_row_id')}
        text=json.dumps(pointer,ensure_ascii=False,indent=2)
        raw=('{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
             '"items":[{"question":"  original  ","reference_links":['+text+']}]}').encode()
        parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        f.seed_reference_catalog(synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch=self.batch(raw)
            item=IntakeItem.objects.create(**self.item_values(batch,parsed))
            values=self.reference_values(item,parsed)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            with self.assertRaises(DatabaseError),transaction.atomic():
                IntakeReference.objects.create(**(values|dict(reference_status='VERIFIED',
                    verified_identity=dict(c.VERIFIED_IDENTITIES[1]),citation_text='mismatched')))
            ref=IntakeReference.objects.create(**(values|dict(reference_status='VERIFIED',
                verified_identity=identity,citation_text='Synthetic verified reference')))
        ref.refresh_from_db()
        self.assertEqual(ref.original_pointer,text)
        self.assertEqual(ref.verified_identity,identity)

    def test_nonempty_0003_upgrade_restores_exact_source_slices_and_keeps_statuses(self):
        with self.probe() as probe:
            g.initialize_synthetic_database(synthetic_fixtures_only=True)
            env=dict(os.environ,PGDATABASE=probe.settings_dict['NAME'],PGTESTDATABASE=probe.settings_dict['TEST']['NAME'])
            root=Path(__file__).resolve().parents[2]
            def command(*args):
                result=subprocess.run([sys.executable,*args],cwd=root,env=env,capture_output=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stderr.decode())
                return result.stdout
            command('manage.py','migrate','intake_workflow','0003','--noinput','--settings=config.settings.wave7_test')
            # Historical models insert only fabricated old-schema fixtures. The
            # ownership guard precedes this fixture transaction; no app service bypass.
            command('-c',"""
import django,hashlib,json
django.setup()
from django.db import connection,transaction
from django.db.migrations.executor import MigrationExecutor
from apps.intake_workflow import fixtures as f,guards as g
g.require_owned_database(synthetic_fixtures_only=True)
apps=MigrationExecutor(connection).loader.project_state([('intake_workflow','0003_review_integrity')]).apps
B=apps.get_model('intake_workflow','IntakeBatch'); I=apps.get_model('intake_workflow','IntakeItem'); R=apps.get_model('intake_workflow','IntakeReference')
raw=f.synthetic_payload(); rows=json.loads(raw)['items']
with transaction.atomic():
    with connection.cursor() as cur: cur.execute("SELECT set_config('fatwa.wave7_synthetic_write',%s,true)",[g.WRITE_TAG])
    b=B.objects.create(idempotency_key='old-fixture',original_payload=raw,payload_sha256=hashlib.sha256(raw).hexdigest())
    one=I.objects.create(batch=b,row_ordinal=1,external_id=rows[0]['external_id'],question_original=rows[0]['question'],original_row=rows[0],intake_status='NEEDS_REVIEW')
    I.objects.create(batch=b,row_ordinal=8,original_row=None,intake_status='BLOCKED_INVALID')
    R.objects.create(intake_item=one,reference_ordinal=1,original_pointer=rows[0]['reference_links'][0])
""")
            checked=subprocess.run([sys.executable,'-c',
                'import django;django.setup();from apps.intake_workflow.guards import require_synthetic_write;'
                'require_synthetic_write(synthetic_fixtures_only=True)'],cwd=root,env=env,capture_output=True,timeout=30)
            self.assertNotEqual(checked.returncode,0)
            self.assertIn(b'WORKFLOW_SCHEMA_NOT_READY',checked.stderr)
            command('manage.py','migrate','--noinput','--settings=config.settings.wave7_test')
            with probe.cursor() as cursor:
                cursor.execute('SELECT original_payload,payload_sha256,payload_snapshot FROM intake_workflow_intakebatch')
                raw,pin,snapshot=cursor.fetchone()
                cursor.execute('SELECT row_ordinal,original_row,source_byte_start,source_byte_end,intake_status '
                               'FROM intake_workflow_intakeitem ORDER BY row_ordinal')
                rows=cursor.fetchall()
                cursor.execute('SELECT original_pointer,source_byte_start,source_byte_end FROM intake_workflow_intakereference')
                pointer,left,right=cursor.fetchone()
            raw=bytes(raw);parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
            self.assertEqual((raw,pin,snapshot),(f.synthetic_payload(),hashlib.sha256(raw).hexdigest(),raw.decode()))
            for ordinal,text,left_row,right_row,status in rows:
                source=parsed.item_sources[ordinal-1]
                self.assertEqual((text,left_row,right_row),(source.text,source.start,source.end))
                self.assertEqual(status,'NEEDS_REVIEW' if ordinal==1 else 'BLOCKED_INVALID')
            source=parsed.reference_sources[0][0]
            self.assertEqual((pointer,left,right),(source.text,source.start,source.end))
