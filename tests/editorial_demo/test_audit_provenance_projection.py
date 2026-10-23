"""Pure projection evidence using fabricated DTOs, never owner-source acceptance."""

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timedelta, timezone, tzinfo
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase

from apps.editorial_demo import workflow_audit_provenance as provenance
from apps.editorial_demo.workflow_audit import AuditDataError
from apps.intake_workflow import review


def synthetic_worklist():
    """Small hand-built read window; source text deliberately remains opaque."""
    when = datetime(2026, 10, 23, 8, 0, 0, 123456, tzinfo=timezone.utc)
    reference = review.StoredReference(
        UUID(int=21), '  {"source_id":"synthetic-أ","heading_id":"1"}\n',
        34, 91, 'UNVERIFIED', '',
    )
    first = review.StoredReviewEvent(
        UUID(int=31), UUID(int=41), 'start_review', 'UNREVIEWED', 'IN_REVIEW',
        '  سبب اصطناعي\tأ\n', when + timedelta(minutes=1),
    )
    second = review.StoredReviewEvent(
        UUID(int=32), UUID(int=42), 'request_changes', 'IN_REVIEW', 'NEEDS_CHANGES',
        'سبب آخر', when + timedelta(minutes=2),
    )
    row = review.StoredReviewRow(
        UUID(int=11), UUID(int=1), 7, 'SYN-أ', '  أ\tأ\n',
        '  {"external_id":"SYN-أ"}\n', 12, 100, 'READY_FOR_EDITOR',
        'NEEDS_CHANGES', 'https://example.invalid/synthetic.mp4',
        (reference,), (second, first), True,
    )
    return review.ReviewWorklist(
        (review.ReviewBatchOption(UUID(int=1), when),), UUID(int=1), (row,), row,
        3, 2, 2, 2, 1, '  أ ', 'exact', '', '',
    )


class AuditProvenanceProjectionTests(SimpleTestCase):
    def setUp(self):
        self.stored = synthetic_worklist()

    def project(self, stored=None):
        return provenance.build_audit_provenance(
            self.stored if stored is None else stored, synthetic_fixtures_only=True,
        )

    def test_projection_retains_original_sources_and_operation_identities(self):
        before = asdict(self.stored)
        result = self.project()
        self.assertIs(result.worklist, self.stored)
        self.assertIs(result.batch, self.stored.batches[0])
        self.assertIs(result.selected_row, self.stored.row)
        self.assertIs(result.references, self.stored.row.references)
        self.assertIs(result.references[0], self.stored.row.references[0])
        self.assertEqual(result.selected_row.source_byte_start, 12)
        self.assertEqual(result.references[0].source_byte_end, 91)
        self.assertEqual([item.entry.source.id for item in result.chronology],
                         [UUID(int=1), UUID(int=31), UUID(int=32)])
        self.assertIs(result.chronology[1].entry.source, self.stored.row.events[1])
        self.assertEqual(result.chronology[1].entry.source.operation_id, UUID(int=41))
        self.assertIs(result.chronology[1].entry.source.created_at,
                      self.stored.row.events[1].created_at)
        self.assertEqual(asdict(self.stored), before)
        self.assertEqual(result, self.project())

    def test_scope_discloses_current_references_partial_window_and_batch_marker(self):
        result = self.project()
        self.assertFalse(result.complete_history)
        self.assertTrue(result.references_are_current_state)
        self.assertFalse(result.batch_timestamp_is_row_intake_time)
        self.assertEqual(result.event_limit, 100)
        self.assertTrue(result.events_truncated)
        self.assertTrue(result.synthetic_fixtures_declared)
        self.assertFalse(result.synthetic_declaration_is_proof)
        untruncated = self.project(replace(
            self.stored, row=replace(self.stored.row, events_truncated=False),
        ))
        self.assertFalse(untruncated.events_truncated)
        self.assertFalse(untruncated.complete_history)

    def test_literal_acknowledgement_is_required_even_without_selection(self):
        empty = replace(self.stored, row=None)
        for acknowledgement in (False, None, 1, 'true'):
            with self.subTest(acknowledgement=acknowledgement):
                with self.assertRaises(AuditDataError):
                    provenance.build_audit_provenance(
                        empty, synthetic_fixtures_only=acknowledgement,
                    )
        with self.assertRaises(AuditDataError):
            provenance.build_audit_provenance(empty)

    def test_empty_selection_and_unstarted_review_never_invent_events_or_times(self):
        empty = self.project(replace(self.stored, row=None))
        self.assertIsNone(empty.selected_row)
        self.assertIsNone(empty.batch)
        self.assertIsNone(empty.events_truncated)
        self.assertEqual(empty.references, ())
        self.assertEqual(empty.chronology, ())
        no_events = self.project(replace(
            self.stored, row=replace(self.stored.row, events=(), events_truncated=False),
        ))
        self.assertEqual(len(no_events.chronology), 1)
        self.assertEqual(no_events.chronology[0].entry.kind, 'batch')
        self.assertFalse(no_events.batch_timestamp_is_row_intake_time)

    def test_selected_row_outside_page_retains_reference_order_and_batch_marker(self):
        row = self.stored.row
        second_reference = replace(row.references[0], id=UUID(int=22),
                                   original_pointer='  unmapped synthetic pointer\t',
                                   source_byte_start=92, source_byte_end=99)
        selected = replace(row, references=(second_reference, *row.references))
        # Timestamps are ordered, not repaired: this DTO asserts no causal proof.
        batch = replace(self.stored.batches[0], created_at=(
            self.stored.batches[0].created_at + timedelta(minutes=3)
        ))
        stored = replace(self.stored, row=selected, rows=(), batches=(batch,),
                         matched_count=0, page=1, page_count=1)
        result = self.project(stored)
        self.assertEqual(result.worklist.rows, ())
        self.assertIs(result.selected_row, selected)
        self.assertIs(result.references, selected.references)
        self.assertEqual([reference.id for reference in result.references],
                         [UUID(int=22), UUID(int=21)])
        self.assertEqual(result.references[0].original_pointer, '  unmapped synthetic pointer\t')
        self.assertEqual([entry.entry.kind for entry in result.chronology],
                         ['review', 'review', 'batch'])
        self.assertIs(result.batch, batch)

    def test_utc_chronology_handles_repeated_hour_and_keeps_original_time(self):
        class RepeatedHour(tzinfo):
            def utcoffset(self, value):
                return timedelta(hours=1 - value.fold)

            def dst(self, value):
                return timedelta(0)

        zone = RepeatedHour()
        early = replace(self.stored.row.events[1], created_at=datetime(
            2026, 10, 25, 1, 45, 0, 654321, tzinfo=zone, fold=0,
        ))
        late = replace(self.stored.row.events[0], created_at=datetime(
            2026, 10, 25, 1, 15, 0, 123456, tzinfo=zone, fold=1,
        ))
        result = self.project(replace(self.stored, row=replace(
            self.stored.row, events=(late, early),
        )))
        self.assertEqual([item.instant_utc.isoformat() for item in result.chronology[1:]],
                         ['2026-10-25T00:45:00.654321+00:00',
                          '2026-10-25T01:15:00.123456+00:00'])
        self.assertIs(result.chronology[1].entry.source, early)
        self.assertIs(result.chronology[2].entry.source, late)
        self.assertEqual(result.chronology[1].entry.timestamp,
                         '2026-10-25T01:45:00.654321+01:00')

    def test_equal_instants_order_batch_then_uuid_across_offsets(self):
        instant = self.stored.batches[0].created_at
        events = tuple(replace(event, created_at=instant.astimezone(
            timezone(timedelta(hours=3)),
        )) for event in self.stored.row.events)
        result = self.project(replace(self.stored, row=replace(self.stored.row, events=events)))
        self.assertEqual([item.entry.source.id for item in result.chronology],
                         [UUID(int=1), UUID(int=31), UUID(int=32)])
        self.assertEqual(tuple(item.instant_utc for item in result.chronology), (instant,) * 3)
        self.assertEqual(result.chronology[1].entry.timestamp,
                         '2026-10-23T11:00:00.123456+03:00')

    def test_projection_and_chronology_are_immutable(self):
        result = self.project()
        for target, attribute, value in (
            (result, 'complete_history', True),
            (result, 'selected_row', None),
            (result.chronology[0], 'instant_utc', None),
            (result.chronology[1].entry, 'source', None),
            (result.references[0], 'original_pointer', 'replaced'),
        ):
            with self.subTest(attribute=attribute), self.assertRaises(FrozenInstanceError):
                setattr(target, attribute, value)

    def test_bounded_window_accepts_limits_and_rejects_overflow(self):
        row = self.stored.row
        references = tuple(replace(row.references[0], id=UUID(int=100 + i)) for i in range(100))
        events = tuple(replace(row.events[0], id=UUID(int=300 + i),
                              operation_id=UUID(int=500 + i)) for i in range(100))
        bounded = replace(self.stored, page_size=50, rows=(row,) * 50,
                          batches=self.stored.batches + tuple(
                              review.ReviewBatchOption(UUID(int=1000 + i),
                                                       self.stored.batches[0].created_at)
                              for i in range(100)),
                          row=replace(row, references=references, events=events))
        result = self.project(bounded)
        self.assertEqual(len(result.references), 100)
        self.assertEqual(len(result.chronology), 101)
        cases = (
            replace(bounded, page_size=0), replace(bounded, page_size=51),
            replace(bounded, rows=bounded.rows + (row,)),
            replace(bounded, batches=bounded.batches + (bounded.batches[-1],)),
            replace(bounded, row=replace(row, references=references + references[:1])),
            replace(bounded, row=replace(row, events=events + events[:1])),
            replace(self.stored, row=None, rows=(replace(row, references=references * 2),)),
            replace(self.stored, row=None, rows=(replace(row, events=events * 2),)),
        )
        for index, stored in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(AuditDataError):
                self.project(stored)

    def test_mutable_collections_and_ambiguous_authoritative_timeline_fail_closed(self):
        row = self.stored.row
        event = row.events[0]
        cases = (
            None,
            replace(self.stored, rows=list(self.stored.rows)),
            replace(self.stored, batches=list(self.stored.batches)),
            replace(self.stored, row=replace(row, references=list(row.references))),
            replace(self.stored, row=replace(row, events=list(row.events))),
            replace(self.stored, batches=()),
            replace(self.stored, row=replace(row, batch_id=UUID(int=99))),
            replace(self.stored, row=replace(row, events=(event, event))),
            replace(self.stored, row=replace(row, events=(replace(
                event, created_at=datetime(2026, 10, 23),
            ),))),
        )
        for index, stored in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(AuditDataError):
                provenance.build_audit_provenance(stored, synthetic_fixtures_only=True)

    def test_projection_requires_no_file_network_or_database_access(self):
        # The DTO is already loaded. Any attempt to fetch more provenance fails.
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
                patch('socket.socket', side_effect=AssertionError('network I/O')), \
                patch.object(review, 'load_review_worklist',
                             side_effect=AssertionError('reader I/O')):
            result = self.project()
        self.assertEqual(len(result.chronology), 3)
        self.assertIs(result.selected_row, self.stored.row)

    def test_malformed_collections_and_bounds_fail_before_timeline_traversal(self):
        cases = (
            None,
            replace(self.stored, batches=None),
            replace(self.stored, batches=(None,)),
            replace(self.stored, batches=self.stored.batches * 102),
            replace(self.stored, rows=None),
            replace(self.stored, rows=(None,)),
            replace(self.stored, rows=self.stored.rows * 2),
            replace(self.stored, row={}),
            replace(self.stored, row=replace(self.stored.row, references=None)),
            replace(self.stored, row=replace(self.stored.row, events=None)),
        )
        for selected in (True, False):
            for index, stored in enumerate(cases):
                if not selected and stored is not None:
                    stored = replace(stored, row=None)
                    # These cases only corrupt selection, which is now absent.
                    if index >= 7:
                        continue
                with self.subTest(selected=selected, case=index):
                    with patch.object(provenance, 'build_audit_timeline',
                                      side_effect=AssertionError('premature traversal')):
                        with self.assertRaises(AuditDataError):
                            provenance.build_audit_provenance(
                                stored, synthetic_fixtures_only=True,
                            )

    def test_non_dto_members_fail_before_timeline_for_all_retained_collections(self):
        row = self.stored.row
        cases = (
            replace(self.stored, batches=({},)),
            replace(self.stored, rows=({},)),
            replace(self.stored, row=replace(row, references=({},))),
            replace(self.stored, row=replace(row, events=({},))),
            replace(self.stored, rows=(replace(row, references=({},)),)),
            replace(self.stored, rows=(replace(row, events=({},)),)),
            replace(self.stored, row=None, rows=(replace(row, references=({},)),)),
            replace(self.stored, row=None, rows=(replace(row, events=({},)),)),
        )
        for index, stored in enumerate(cases):
            with self.subTest(case=index):
                with patch.object(provenance, 'build_audit_timeline',
                                  side_effect=AssertionError('premature traversal')):
                    with self.assertRaises(AuditDataError):
                        self.project(stored)

    def test_mutable_scalar_fields_cannot_hide_inside_frozen_source_dtos(self):
        row = self.stored.row
        cases = (
            replace(self.stored, q={}),
            replace(self.stored, batches=(replace(self.stored.batches[0], created_at={}),)),
            replace(self.stored, row=replace(row, question={})),
            replace(self.stored, row=replace(row, references=(replace(
                row.references[0], original_pointer={},
            ),))),
            replace(self.stored, row=None, rows=(replace(row, events=(replace(
                row.events[0], reason={},
            ),)),)),
        )
        for index, stored in enumerate(cases):
            with self.subTest(case=index):
                with patch.object(provenance, 'build_audit_timeline',
                                  side_effect=AssertionError('premature traversal')):
                    with self.assertRaises(AuditDataError):
                        self.project(stored)
