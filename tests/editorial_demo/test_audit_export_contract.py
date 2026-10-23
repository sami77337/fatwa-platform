"""Pure synthetic DTO boundary tests; no database or original archive evidence."""

import hashlib
import json
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from unittest import TestCase
from uuid import UUID

from apps.editorial_demo.workflow_audit import AuditDataError, serialize_audit_json
from apps.intake_workflow import contracts as c, fixtures, review


def synthetic_export():
    parsed = c.parse_synthetic_payload(fixtures.synthetic_payload(), synthetic_fixtures_only=True)
    source, pointer = parsed.item_sources[0], parsed.reference_sources[0][0]
    when = datetime(2026, 10, 22, 8, 0, 0, 123456, tzinfo=timezone.utc)
    event = review.StoredReviewEvent(UUID(int=31), UUID(int=41), 'start_review',
        'UNREVIEWED', 'IN_REVIEW', '  سبب اصطناعي\tأ\n  ', when)
    reference = review.StoredReference(UUID(int=21), pointer.text, pointer.start, pointer.end,
                                       'VERIFIED', 'استشهاد اصطناعي')
    row = review.StoredReviewRow(UUID(int=11), UUID(int=1), 1, parsed.items[0]['external_id'],
        parsed.items[0]['question'], source.text, source.start, source.end,
        'READY_FOR_EDITOR', 'IN_REVIEW', parsed.items[0]['prepared_clip_url'],
        (reference,), (event,), True)
    return review.ReviewWorklist((review.ReviewBatchOption(UUID(int=1), when),), UUID(int=1),
        (row,), row, 1, 1, 1, 1, 20, 'أ', 'normalized', '', '')


class AuditExportContractTests(TestCase):
    def setUp(self):
        self.stored = synthetic_export()

    def rejected(self, stored):
        with self.assertRaises(AuditDataError) as caught:
            serialize_audit_json(stored)
        self.assertLessEqual(len(str(caught.exception)), 64)
        self.assertNotIn('PRIVATE_SENTINEL', str(caught.exception))

    def test_valid_export_keeps_existing_bytes_and_source_objects(self):
        before = self.stored
        snapshot = asdict(before)
        content = serialize_audit_json(before)
        self.assertEqual(hashlib.sha256(content).hexdigest(),
                         '497bdf0ec85f7a5f1aeea8e560955e3974882a1dd172e1c8d505c7c9e2ca2248')
        self.assertEqual(asdict(self.stored), snapshot)
        decoded = json.loads(content)
        self.assertEqual(decoded['worklist']['rows'][0]['original_row'], before.row.original_row)
        self.assertEqual(decoded['timeline'][1]['source']['reason'], '  سبب اصطناعي\tأ\n  ')
        self.assertEqual(decoded['timeline'][1]['source']['created_at'],
                         '2026-10-22T08:00:00.123456+00:00')

    def test_worklist_scalars_reject_wrong_json_types(self):
        cases = {'page_size': True, 'page': '1', 'page_count': 1.0,
                 'total_count': False, 'matched_count': None, 'batch_id': str(UUID(int=1)),
                 'q': {'PRIVATE_SENTINEL': 1}, 'mode': [], 'intake_status': 0,
                 'review_status': False}
        for field, value in cases.items():
            with self.subTest(field=field):
                self.rejected(replace(self.stored, **{field: value}))

    def test_collections_are_bounded_dto_tuples_even_without_detail(self):
        base = replace(self.stored, row=None)
        for field, value in (('rows', list(base.rows)), ('batches', list(base.batches)),
                             ('rows', ({'PRIVATE_SENTINEL': 1},)),
                             ('batches', ({'PRIVATE_SENTINEL': 1},))):
            with self.subTest(field=field, value=value):
                self.rejected(replace(base, **{field: value}))

    def test_unselected_batches_require_uuid_and_aware_datetime(self):
        for invalid in (replace(self.stored.batches[0], id='PRIVATE_SENTINEL'),
                        replace(self.stored.batches[0], created_at='PRIVATE_SENTINEL'),
                        replace(self.stored.batches[0], created_at=datetime(2026, 10, 22))):
            self.rejected(replace(self.stored, row=None, batches=(invalid,)))

    def test_page_rows_reject_wrong_field_types_without_detail(self):
        cases = {'id': 'PRIVATE_SENTINEL', 'batch_id': None, 'row_ordinal': True,
                 'external_id': {}, 'question': [], 'original_row': 12,
                 'source_byte_start': False, 'source_byte_end': '10',
                 'intake_status': [], 'review_status': {}, 'prepared_clip_url': False,
                 'events_truncated': 1, 'references': [], 'events': []}
        for field, value in cases.items():
            with self.subTest(field=field):
                row = replace(self.stored.row, **{field: value})
                self.rejected(replace(self.stored, row=None, rows=(row,)))

    def test_nested_reference_and_event_fields_cannot_inject_json(self):
        reference, event = self.stored.row.references[0], self.stored.row.events[0]
        bad_references = [None] + [replace(reference, **{field: value}) for field, value in (
            ('id', 'PRIVATE_SENTINEL'), ('original_pointer', {}), ('source_byte_start', True),
            ('source_byte_end', '20'), ('reference_status', []), ('citation_text', {}))]
        bad_events = [None] + [replace(event, **{field: value}) for field, value in (
            ('id', 'PRIVATE_SENTINEL'), ('operation_id', None), ('action', {}),
            ('from_status', []), ('to_status', False), ('reason', {}),
            ('created_at', datetime(2026, 10, 22)))]
        for collection, values in (('references', bad_references), ('events', bad_events)):
            for value in values:
                with self.subTest(collection=collection, value=value):
                    row = replace(self.stored.row, **{collection: (value,)})
                    self.rejected(replace(self.stored, row=None, rows=(row,)))

    def test_invalid_unicode_fails_with_sanitized_contract_error(self):
        for field in ('question', 'original_row', 'external_id', 'prepared_clip_url'):
            row = replace(self.stored.row, **{field: 'PRIVATE_SENTINEL\ud800'})
            with self.subTest(field=field):
                self.rejected(replace(self.stored, rows=(row,), row=None))
        self.rejected(replace(self.stored, q='PRIVATE_SENTINEL\ud800'))

    def test_dataclass_extensions_cannot_silently_expand_v1_schema(self):
        @dataclass(frozen=True, slots=True)
        class ExtendedRow(review.StoredReviewRow):
            private_extra: str = 'PRIVATE_SENTINEL'

        row = ExtendedRow(**{field.name: getattr(self.stored.row, field.name)
                             for field in fields(review.StoredReviewRow)})
        self.rejected(replace(self.stored, rows=(row,), row=None))
