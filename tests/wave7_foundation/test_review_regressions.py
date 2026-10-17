"""Adversarial regressions for the independent PR58 foundation review."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from django.conf import settings
from django.db import connection, DatabaseError, transaction
from django.test import TransactionTestCase

from apps.intake_workflow import contracts as c, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem
from . import test_database as foundation


class ReviewRegressionTests(TransactionTestCase):
    probe = foundation.FoundationDatabaseTests.probe

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context = g.require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != settings.WAVE7_TEST_DATABASE_NAME:
            raise RuntimeError('Review regressions require the selected disposable test DB')

    def batch(self, raw, via='orm'):
        values = dict(idempotency_key=uuid4().hex, original_payload=raw,
                      payload_sha256=hashlib.sha256(raw).hexdigest())
        if via == 'orm':
            return IntakeBatch.objects.create(**values)
        model = IntakeBatch(**values)
        if via == 'bulk':
            return IntakeBatch.objects.bulk_create([model])[0]
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO intake_workflow_intakebatch '
                '(id,scope,idempotency_key,original_payload,payload_sha256,payload_snapshot,'
                'contract_version,source_config_id,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                [model.pk,c.SYNTHETIC_SCOPE,model.idempotency_key,raw,model.payload_sha256,'',
                 c.CONTRACT_VERSION,c.SOURCE_CONFIG_ID,datetime.now(timezone.utc)])
        return model

    def item(self, batch, row, *, via='orm', external_id=None, ordinal=1):
        parsed=c.parse_synthetic_payload(bytes(batch.original_payload),synthetic_fixtures_only=True)
        source=parsed.item_sources[ordinal-1]
        values = dict(batch=batch,row_ordinal=ordinal,original_row=source.text,external_id=external_id,
            source_byte_start=source.start,source_byte_end=source.end,
            question_original=row.get('question') if isinstance(row,dict) and isinstance(row.get('question'),str) else None,
            intake_status='BLOCKED_INVALID')
        if via == 'orm':
            return IntakeItem.objects.create(**values)
        model = IntakeItem(**values)
        if via == 'bulk':
            return IntakeItem.objects.bulk_create([model])[0]
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO intake_workflow_intakeitem '
                '(id,batch_id,row_ordinal,external_id,question_original,original_row,intake_status,'
                'review_status,validation_results,source_byte_start,source_byte_end) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)',
                [model.pk,batch.pk,ordinal,external_id,model.question_original,source.text,
                 model.intake_status,model.review_status,'{}',source.start,source.end])
        return model

    def test_unknown_schema_and_standalone_types_never_claim_or_migrate(self):
        cases = (
            ('ordinary_pg_prefix_schema', [
                'CREATE SCHEMA pgxforeign', 'CREATE TABLE pgxforeign.unknown_existing (value integer)',
                'INSERT INTO pgxforeign.unknown_existing VALUES (73)']),
            ('public_enum', ["CREATE TYPE public.unknown_enum AS ENUM ('original')"]),
            ('public_domain', ['CREATE DOMAIN public.unknown_domain AS integer CHECK (VALUE > 0)']),
            ('public_range', ['CREATE TYPE public.unknown_range AS RANGE (subtype=integer)']),
        )
        for label, statements in cases:
            with self.subTest(target=label), self.probe() as probe:
                with probe.cursor() as cursor:
                    for statement in statements:
                        cursor.execute(statement)
                try:
                    g.initialize_synthetic_database(synthetic_fixtures_only=True)
                    denied = False
                except g.SyntheticWriteDenied as exc:
                    denied = exc.code == 'UNKNOWN_NONEMPTY_DATABASE'
                env = dict(os.environ,PGDATABASE=probe.settings_dict['NAME'],
                           PGTESTDATABASE=probe.settings_dict['TEST']['NAME'])
                result = subprocess.run([sys.executable,'manage.py','migrate','--noinput',
                    '--settings=config.settings.wave7_test'],cwd=Path(__file__).resolve().parents[2],
                    env=env,capture_output=True,timeout=30)
                with probe.cursor() as cursor:
                    cursor.execute("SELECT to_regclass('public.wave7_synthetic_ownership'), "
                                   "to_regclass('public.django_migrations')")
                    marker, records = cursor.fetchone()
                    if label == 'ordinary_pg_prefix_schema':
                        cursor.execute('SELECT value FROM pgxforeign.unknown_existing')
                        self.assertEqual(cursor.fetchall(), [(73,)])
                self.assertEqual((denied,result.returncode != 0,marker,records),
                                 (True,True,None,None))

    def test_duplicate_json_keys_reject_orm_bulk_and_raw_before_jsonb(self):
        prefix = b'{"schema":"fatwa.wave7.synthetic-intake.v1",'
        cases = (
            prefix + b'"synthetic_fixtures_only":false,"synthetic_fixtures_only":true,"items":[{}]}',
            prefix + b'"synthetic_fixtures_only":true,"items":[{"question":"first","question":"last"}]}',
            prefix + b'"synthetic_fixtures_only":true,"items":[{"question":"first","\\u0071uestion":"last"}]}',
            prefix + b'"synthetic_fixtures_only":true,"items":[{"reference_links":[{"source_id":"a","source_id":"b"}]}]}',
        )
        for raw in cases:
            with self.assertRaises(c.ContractError):
                c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
            for via in ('orm','bulk','raw'):
                with self.subTest(via=via,raw=raw),g.synthetic_atomic(synthetic_fixtures_only=True):
                    with self.assertRaises(DatabaseError),transaction.atomic():
                        self.batch(raw,via)
        self.assertEqual(IntakeBatch.objects.count(),0)

    def test_owned_previous_schema_has_no_write_permission_before_review_migration(self):
        with self.probe() as probe:
            g.initialize_synthetic_database(synthetic_fixtures_only=True)
            env = dict(os.environ,PGDATABASE=probe.settings_dict['NAME'],
                       PGTESTDATABASE=probe.settings_dict['TEST']['NAME'])
            migrated = subprocess.run([sys.executable,'manage.py','migrate','intake_workflow','0002',
                '--noinput','--settings=config.settings.wave7_test'],
                cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,timeout=30)
            self.assertEqual(migrated.returncode,0,migrated.stderr.decode())
            checked = subprocess.run([sys.executable,'-c',
                'import django; django.setup(); from apps.intake_workflow.guards import require_synthetic_write; '
                'require_synthetic_write(synthetic_fixtures_only=True)'],
                cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,timeout=30)
            self.assertNotEqual(checked.returncode,0)
            self.assertIn(b'WORKFLOW_SCHEMA_NOT_READY',checked.stderr)

    def test_invalid_external_id_rejects_all_write_paths_but_null_retains_original(self):
        values = list(dict.fromkeys([
            ' padded ','   ','\u00a0ID\u00a0','\u2003ID','ID\u202f',
            *(ch+'ID'+ch for ch in c.EXTERNAL_ID_EDGE_WHITESPACE),
            *('I'+chr(code)+'D' for code in (*range(1,32),*range(127,160))),
        ]))
        for value in values:
            row = dict(external_id=value,question='  original\tquestion\n ')
            raw = json.dumps(dict(schema=c.PAYLOAD_SCHEMA,synthetic_fixtures_only=True,items=[row]),
                             ensure_ascii=False).encode()
            self.assertIsNone(c.valid_external_id(value))
            for via in ('orm','bulk','raw'):
                with self.subTest(value=value,via=via):
                    with g.synthetic_atomic(synthetic_fixtures_only=True):
                        batch = self.batch(raw)
                    with g.synthetic_atomic(synthetic_fixtures_only=True):
                        with self.assertRaises(DatabaseError),transaction.atomic():
                            self.item(batch,row,via=via,external_id=value)
                        item = self.item(batch,row,via=via,external_id=None)
                    item.refresh_from_db()
                    self.assertIsNone(item.external_id)
                    self.assertEqual(item.original_row,json.dumps(row,ensure_ascii=False))
                    self.assertEqual(item.question_original,row['question'])

        # Interior whitespace and exact valid Unicode IDs must not be trimmed/rejected.
        for value in ('OPAQUE/ROW-1','I D','I\u00a0D','مُعرِّف-١'):
            row = dict(external_id=value,question='  original  ')
            raw = json.dumps(dict(schema=c.PAYLOAD_SCHEMA,synthetic_fixtures_only=True,items=[row]),
                             ensure_ascii=False).encode()
            self.assertEqual(c.valid_external_id(value),value)
            for via in ('orm','bulk','raw'):
                with self.subTest(valid_id=value,via=via),g.synthetic_atomic(synthetic_fixtures_only=True):
                    batch = self.batch(raw)
                    item = self.item(batch,row,via=via,external_id=value)
                    item.refresh_from_db()
                    self.assertEqual(item.external_id,value)

