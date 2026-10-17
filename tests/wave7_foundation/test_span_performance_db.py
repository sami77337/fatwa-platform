"""Bounded lossless INSERT evidence on the actual owned PostgreSQL database."""
import hashlib
import json
import time
from uuid import uuid4

from django.db import connection, DatabaseError, transaction
from django.test import TransactionTestCase

from apps.intake_workflow import contracts as c, guards as g
from apps.intake_workflow.intake import import_intake
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference


def payload(rows):
    return json.dumps(dict(schema='fatwa.wave7.synthetic-intake.v1',
        synthetic_fixtures_only=True, items=rows), ensure_ascii=False,
        separators=(',', ':')).encode()


def source_row(ident):
    return dict(external_id=ident, question='  سُؤَالٌ أصلي\t\n  ',
        prepared_clip_url='https://example.invalid/span.mp4',
        reference_links=[dict(source_id='W7-SOURCE', heading_id='W7-HEADING-2')])


class SourceSpanPerformanceTests(TransactionTestCase):
    def timeout(self):
        g.require_synthetic_write(synthetic_fixtures_only=True)
        with connection.cursor() as cursor:
            cursor.execute('SHOW statement_timeout')
            self.assertEqual(cursor.fetchone()[0], '3s')

    def ingest(self, raw):
        return import_intake(raw, idempotency_key=uuid4().hex,
                             synthetic_fixtures_only=True)

    def batch(self, raw):
        return IntakeBatch.objects.create(idempotency_key=uuid4().hex,
            original_payload=raw, payload_sha256=hashlib.sha256(raw).hexdigest())

    def item(self, batch, parsed, ordinal):
        row = parsed.items[ordinal-1]
        source = parsed.item_sources[ordinal-1]
        return IntakeItem(batch=batch, row_ordinal=ordinal, original_row=source.text,
            source_byte_start=source.start, source_byte_end=source.end,
            question_original=row.get('question') if isinstance(row, dict) else None,
            intake_status='BLOCKED_INVALID')

    def test_million_bytes_800_rows_and_references_keep_exact_source_under_three_seconds_per_statement(self):
        self.timeout()
        rows = [source_row('span-' + str(n)) for n in range(800)]
        remaining = c.MAX_INPUT_BYTES-len(payload(rows))
        for n, row in enumerate(rows):
            row['question'] += 'x' * (remaining//800 + (n < remaining % 800))
        raw = payload(rows)
        self.assertEqual(len(raw), 1_000_000)
        insert_seconds = []
        def measure_insert(execute, sql, params, many, context):
            started = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                if sql.lstrip().startswith('INSERT INTO "intake_workflow_intakeitem"'):
                    insert_seconds.append(time.perf_counter()-started)
        started = time.perf_counter()
        with connection.execute_wrapper(measure_insert):
            receipt = self.ingest(raw)
        elapsed = time.perf_counter()-started
        batch = IntakeBatch.objects.get(pk=receipt.batch_id)
        self.assertEqual((bytes(batch.original_payload), batch.payload_snapshot.encode(),
                          batch.payload_sha256), (raw, raw, hashlib.sha256(raw).hexdigest()))
        items = list(batch.items.order_by('row_ordinal'))
        refs = list(IntakeReference.objects.filter(intake_item__batch=batch))
        self.assertEqual((len(items), len(refs), receipt.item_count, receipt.reference_count),
                         (800, 800, 800, 800))
        for item, row in zip(items, rows, strict=True):
            self.assertEqual(item.question_original, row['question'])
            self.assertEqual(item.intake_status, 'READY_FOR_EDITOR')
            self.assertEqual(raw[item.source_byte_start:item.source_byte_end], item.original_row.encode())
        for ref in refs:
            self.assertEqual(raw[ref.source_byte_start:ref.source_byte_end], ref.original_pointer.encode())
        print('WAVE7_SPAN_PERFORMANCE=' + json.dumps(dict(bytes=len(raw), rows=len(items),
            references=len(refs), import_seconds=round(elapsed, 6), statement_timeout='3s',
            item_insert_statements=len(insert_seconds),
            longest_item_insert_seconds=round(max(insert_seconds), 6),
            payload_sha256=batch.payload_sha256)), flush=True)
        self.timeout()

    def test_full_1000_row_limit_remains_accepted(self):
        self.timeout()
        receipt = self.ingest(payload([source_row('maximum-' + str(n)) for n in range(1000)]))
        self.assertEqual((receipt.item_count, receipt.reference_count), (1000, 1000))
        self.assertEqual(IntakeItem.objects.count(), 1000)

    def test_oversize_and_1001_rows_fail_before_sql_and_storage_keeps_its_bounds(self):
        single = payload([source_row('oversize')])
        raws = [single + b' ' * (c.MAX_INPUT_BYTES+1-len(single)),
                payload([source_row(str(n)) for n in range(1001)])]
        for raw in raws:
            with self.subTest(size=len(raw)), self.assertNumQueries(0):
                with self.assertRaises(c.ContractError):
                    self.ingest(raw)
            with self.subTest(storage_size=len(raw)), g.synthetic_atomic(synthetic_fixtures_only=True):
                with self.assertRaises(DatabaseError), transaction.atomic():
                    self.batch(raw)
        self.assertEqual((IntakeBatch.objects.count(), IntakeItem.objects.count(),
                          IntakeReference.objects.count()), (0, 0, 0))

    def test_sparse_reordered_inserts_from_multiple_batches_keep_structural_ordinals(self):
        raws = [b' {"items":[ {"question":"same"},null,{"question":"same"},1e-20000 ],'
                b'"synthetic_fixtures_only":true,"schema":"fatwa.wave7.synthetic-intake.v1"}\n',
                payload([dict(question='  أُصلي\t\n  '), None, dict(question='last')])]
        parsed = [c.parse_synthetic_payload(raw, synthetic_fixtures_only=True) for raw in raws]
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batches = [self.batch(raw) for raw in raws]
            items = [self.item(batches[index], parsed[index], ordinal)
                     for index, ordinal in [(0, 4), (1, 3), (0, 1), (1, 1), (0, 3)]]
            IntakeItem.objects.bulk_create(items)
        self.assertEqual(IntakeItem.objects.count(), 5)
        for item in IntakeItem.objects.select_related('batch'):
            raw = bytes(item.batch.original_payload)
            self.assertEqual(raw[item.source_byte_start:item.source_byte_end], item.original_row.encode())

    def test_a_shadow_token_cannot_replace_its_structural_row_or_leave_partial_bulk_rows(self):
        raw = payload([dict(question='outer', shadow=dict(question='same')), dict(question='same')])
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = self.batch(raw)
        valid = self.item(batch, parsed, 1)
        forged = self.item(batch, parsed, 2)
        forged.source_byte_start = raw.index(forged.original_row.encode())
        forged.source_byte_end = forged.source_byte_start + len(forged.original_row.encode())
        self.assertNotEqual(forged.source_byte_start, parsed.item_sources[1].start)
        with self.assertRaises(DatabaseError), g.synthetic_atomic(synthetic_fixtures_only=True):
            IntakeItem.objects.bulk_create([valid, forged])
        self.assertEqual(IntakeItem.objects.count(), 0)
        self.assertEqual(bytes(IntakeBatch.objects.get(pk=batch.pk).original_payload), raw)
