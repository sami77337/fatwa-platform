"""Permanent E3 service evidence on a fresh, owned PostgreSQL 17/18 test DB.

Sources are persisted directly using the accepted foundation contract, so these
regressions do not depend on an E1 implementation or a mocked catalog adapter.
"""
import json
import os
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.db import connection, transaction
from django.db.models.query import QuerySet
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.intake_workflow import contracts as c, fixtures as f, guards as g
from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
from apps.intake_workflow.references import verify_batch_references
from apps.reference.models import ReferenceWork, ReferenceEdition, ReferenceHeading
from apps.reference.normalization import normalize_title


def envelope(items):
    return json.dumps(dict(schema=c.PAYLOAD_SCHEMA, synthetic_fixtures_only=True,
                           items=items), ensure_ascii=False).encode()


class PersistedReferenceMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context = g.require_synthetic_write(synthetic_fixtures_only=True)
        if context.database_name != settings.WAVE7_TEST_DATABASE_NAME:
            raise RuntimeError('Reference service tests require the selected disposable test DB')

    def persist(self, raw=None, *, omit_item=None, omit_reference=None):
        raw = f.synthetic_payload() if raw is None else raw
        parsed = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            batch = IntakeBatch.objects.create(idempotency_key=uuid4().hex,
                original_payload=raw, payload_sha256=parsed.payload_sha256)
            for number, (row, source, pointers) in enumerate(zip(parsed.items,
                    parsed.item_sources, parsed.reference_sources, strict=True), 1):
                if number == omit_item:
                    continue
                item = IntakeItem.objects.create(batch=batch, row_ordinal=number,
                    external_id=c.valid_external_id(row.get('external_id')) if isinstance(row, dict) else None,
                    question_original=row.get('question') if isinstance(row, dict)
                        and isinstance(row.get('question'), str) else None,
                    original_row=source.text, source_byte_start=source.start,
                    source_byte_end=source.end, intake_status='BLOCKED_INVALID',
                    validation_results={'synthetic_historical_intake': True})
                for ordinal, pointer in enumerate(pointers, 1):
                    if (number, ordinal) == omit_reference:
                        continue
                    IntakeReference.objects.create(intake_item=item, reference_ordinal=ordinal,
                        original_pointer=pointer.text, source_byte_start=pointer.start,
                        source_byte_end=pointer.end)
        return batch

    def references(self, batch):
        return list(IntakeReference.objects.filter(intake_item__batch=batch)
                    .order_by('intake_item__row_ordinal', 'reference_ordinal').values())

    def verify(self, batch):
        return verify_batch_references(batch.pk, synthetic_fixtures_only=True)


class ReferenceServiceDatabaseTests(PersistedReferenceMixin, TransactionTestCase):
    def setUp(self):
        f.seed_reference_catalog(synthetic_fixtures_only=True)

    def test_current_catalog_preserves_sources_statuses_and_full_provenance(self):
        batch = self.persist()
        items = list(IntakeItem.objects.filter(batch=batch).values())
        originals = [(r['id'], r['original_pointer'], r['source_byte_start'], r['source_byte_end'])
                     for r in self.references(batch)]
        catalog = list(ReferenceHeading.objects.values())
        before_batch = IntakeBatch.objects.values().get(pk=batch.pk)
        result = self.verify(batch)
        self.assertEqual(len(result.items), 8)
        self.assertEqual(items, list(IntakeItem.objects.filter(batch=batch).values()))
        self.assertEqual(before_batch, IntakeBatch.objects.values().get(pk=batch.pk))
        self.assertEqual(catalog, list(ReferenceHeading.objects.values()))
        refs = self.references(batch)
        self.assertEqual(originals, [(r['id'], r['original_pointer'], r['source_byte_start'], r['source_byte_end']) for r in refs])
        self.assertEqual([r['reference_status'] for r in refs], ['VERIFIED'] * 3)
        self.assertEqual(ReviewEvent.objects.count(), 0)
        for ref in refs:
            self.assertFalse(ref['verification_results']['archive_inspected'])
            self.assertEqual(ref['verification_results']['source']['text'], ref['original_pointer'])
            self.assertEqual(ref['verification_results']['source']['start'], ref['source_byte_start'])
            self.assertTrue(ref['citation_text'])
            self.assertEqual(ref['verification_results']['provenance']['source_archive_sha256'], 'a' * 64)

    def test_identical_replay_has_zero_updates(self):
        batch = self.persist()
        first = self.verify(batch)
        with CaptureQueriesContext(connection) as queries:
            second = self.verify(batch)
        self.assertEqual(first, second)
        self.assertFalse(any(q['sql'].lstrip().upper().startswith('UPDATE') for q in queries))

    def test_partial_real_bulk_update_rolls_back_every_derived_field(self):
        batch = self.persist()
        before = self.references(batch)
        original = QuerySet.bulk_update
        changed = []

        def fail_after_first(queryset, objects, fields, **kwargs):
            changed.append(original(queryset, objects[:1], fields, **kwargs))
            raise RuntimeError('synthetic partial write')

        with patch.object(QuerySet, 'bulk_update', fail_after_first):
            with self.assertRaisesRegex(RuntimeError, 'synthetic partial write'):
                self.verify(batch)
        self.assertEqual(changed, [1])  # a real UPDATE occurred before failure
        self.assertEqual(before, self.references(batch))

    def test_actual_postgresql_catalog_read_failure_aborts_without_success(self):
        batch = self.persist()
        self.verify(batch)
        before = self.references(batch)
        failed = []

        def fail_catalog(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith('SELECT') and '"reference_referenceheading"' in sql:
                failed.append(True)
                # Execute an actual failing SELECT, rather than mock the adapter
                # or manufacture DatabaseError before any driver operation.
                return execute('SELECT wave7_missing_column FROM reference_referenceheading LIMIT 1',
                               None, many, context)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_catalog):
            with self.assertRaisesRegex(c.ContractError, 'catalog_unavailable'):
                self.verify(batch)
        self.assertEqual(failed, [True])
        self.assertEqual(before, self.references(batch))
        self.assertEqual(ReviewEvent.objects.count(), 0)

    def test_lossless_numeric_malformed_and_null_sources_are_never_reencoded(self):
        raw = (b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
               b'{"external_id":73.000000000000001,"question":"  original\\t\\n  ",'
               b'"reference_links":[{"unknown":1e-20000},1e-999999999999999999999999,null]},'
               + b'9' * 6000 + b',null]}')
        batch = self.persist(raw)
        sources = [(r['original_pointer'], r['source_byte_start'], r['source_byte_end']) for r in self.references(batch)]
        result = self.verify(batch)
        self.assertEqual(len(result.items), 3)
        for ref, source in zip(self.references(batch), sources, strict=True):
            self.assertEqual((ref['original_pointer'], ref['source_byte_start'], ref['source_byte_end']), source)
            self.assertEqual(raw[source[1]:source[2]], source[0].encode())
            self.assertEqual((ref['reference_status'], ref['verified_identity'], ref['citation_text']), ('UNVERIFIED', {}, ''))
        batch.refresh_from_db()
        self.assertEqual(bytes(batch.original_payload), raw)
        self.assertEqual(batch.payload_snapshot.encode(), raw)

    def test_each_conflicting_c2_identity_field_suppresses_citation(self):
        identity = {k: v for k, v in c.VERIFIED_IDENTITIES[0].items() if k not in ('edition_id', 'source_row_id')}
        pointers = [identity | {key: ('d' * 64 if key.endswith('sha256') else 'other-identity')}
                    for key in identity]
        batch = self.persist(envelope([dict(reference_links=pointers)]))
        self.verify(batch)
        self.assertEqual(len(self.references(batch)), 6)
        for ref in self.references(batch):
            self.assertEqual((ref['reference_status'], ref['verified_identity'], ref['citation_text']), ('MISMATCHED', {}, ''))

    def test_duplicate_and_unmapped_pointers_keep_distinct_original_offsets(self):
        pointer = dict(source_id='W7-SOURCE', heading_id='W7-HEADING-1')
        batch = self.persist(envelope([dict(reference_links=[pointer, pointer,
            dict(source_id='unmapped', heading_id='opaque'), 73, None])]))
        self.verify(batch)
        refs = self.references(batch)
        self.assertEqual([r['reference_status'] for r in refs], ['UNVERIFIED'] * 5)
        self.assertNotEqual(refs[0]['source_byte_start'], refs[1]['source_byte_start'])
        self.assertEqual([r['verification_results']['reasons'][0] for r in refs[:3]],
                         ['duplicate_pointer', 'duplicate_pointer', 'explicit_mapping_missing'])

    def test_incomplete_item_collection_fails_before_any_derived_update(self):
        batch = self.persist(omit_item=6)
        before = self.references(batch)
        with self.assertRaisesRegex(c.ContractError, 'persisted_item_alignment_mismatch'):
            self.verify(batch)
        self.assertEqual(before, self.references(batch))

    def test_incomplete_reference_collection_fails_before_any_derived_update(self):
        batch = self.persist(omit_reference=(4, 1))
        before = self.references(batch)
        with self.assertRaisesRegex(c.ContractError, 'persisted_reference_alignment_mismatch'):
            self.verify(batch)
        self.assertEqual(before, self.references(batch))

    def test_acknowledgement_uuid_alias_and_write_flag_guards_precede_mutation(self):
        batch = self.persist()
        before = self.references(batch)
        for value in (False, None):
            with self.subTest(ack=value), self.assertRaises(c.ContractError):
                verify_batch_references(batch.pk, synthetic_fixtures_only=value)
        with self.assertRaisesRegex(c.ContractError, 'batch_uuid_required'):
            verify_batch_references(str(batch.pk), synthetic_fixtures_only=True)
        with self.assertRaisesRegex(g.SyntheticWriteDenied, 'UNSAFE_DATABASE_ALIAS'):
            verify_batch_references(batch.pk, synthetic_fixtures_only=True, using='untrusted')
        with patch.dict(os.environ, {'FATWA_WAVE7_SYNTHETIC_WRITES': '0'}):
            with self.assertRaisesRegex(g.SyntheticWriteDenied, 'WRITES_DISABLED'):
                self.verify(batch)
        self.assertEqual(before, self.references(batch))

    def test_outer_transaction_is_rejected_and_missing_batch_is_not_success(self):
        batch = self.persist()
        before = self.references(batch)
        with transaction.atomic():
            with self.assertRaisesRegex(g.SyntheticWriteDenied, 'GUARD_BEFORE_TRANSACTION_REQUIRED'):
                self.verify(batch)
        with self.assertRaisesRegex(c.ContractError, 'batch_not_found'):
            verify_batch_references(uuid4(), synthetic_fixtures_only=True)
        self.assertEqual(before, self.references(batch))


class ReferenceCatalogNegativeTests(PersistedReferenceMixin, TransactionTestCase):
    def seed(self, *, wrong_parent=False, wrong_hash=False, wrong_page=False, missing_child=False):
        """Insert negative evidence before normal seed; never mutate source guards."""
        with g.synthetic_atomic(synthetic_fixtures_only=True):
            ReferenceWork.objects.create(pk=7001, source_namespace=c.SOURCE_IDENTITY['source_namespace'],
                source_book_id='622', title_original='مرجع اصطناعي لتجارب Wave7', madhhab='اصطناعي فقط')
            ReferenceEdition.objects.create(pk=7001, work_id=7001,
                edition_key=c.SOURCE_IDENTITY['edition_key'], title='طبعة اصطناعية', publisher='ناشر اصطناعي',
                source_archive_sha256=('d' if wrong_hash else 'a') * 64,
                source_input_sha256='b' * 64, ingest_checksum='c' * 64,
                input_name='wave7-fixed-fabricated-fixture', heading_count=3, root_count=1, max_depth=2)
            def heading(row, title, parent=None, page=None, position=1):
                return ReferenceHeading.objects.create(pk=7000 + row, edition_id=7001,
                    source_id=f'wave7-title-{row}', source_row_id=row, parent_id=parent,
                    source_order=row, position=position, depth=1 if parent is None else 2,
                    source_page_id=row, source_part='الأول', source_page_number=page or 6 + row,
                    title_original=title, title_normalized=normalize_title(title))
            heading(1, 'كِتَابٌ اصطناعي')
            if wrong_parent:
                heading(99, 'كِتَابٌ اصطناعي', position=2)
            if not missing_child:
                heading(2, 'بابٌ اصطناعي أول', 7099 if wrong_parent else 7001,
                        page=80 if wrong_page else 8)

    def child(self):
        return self.persist(envelope([dict(reference_links=[dict(source_id='W7-SOURCE', heading_id='W7-HEADING-2')])]))

    def assert_suppressed(self, batch, status):
        self.verify(batch)
        ref = self.references(batch)[0]
        self.assertEqual((ref['reference_status'], ref['verified_identity'], ref['citation_text']), (status, {}, ''))
        return ref

    def test_same_title_wrong_ancestor_identity_is_mismatched(self):
        self.seed(wrong_parent=True)
        ref = self.assert_suppressed(self.child(), 'MISMATCHED')
        self.assertEqual(ref['verification_results']['reasons'], ['catalog_source_row_mismatch'])

    def test_wrong_archive_hash_is_mismatched(self):
        self.seed(wrong_hash=True)
        self.assert_suppressed(self.child(), 'MISMATCHED')

    def test_wrong_complete_printed_location_is_mismatched(self):
        self.seed(wrong_page=True)
        self.assert_suppressed(self.child(), 'MISMATCHED')

    def test_missing_catalog_heading_is_unverified(self):
        self.seed(missing_child=True)
        self.assert_suppressed(self.child(), 'UNVERIFIED')
