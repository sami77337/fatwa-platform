import json
import socket
import sqlite3
import sys
import unittest
from unittest.mock import patch
from apps.prepared_pipeline import C1Pointer, ExplicitMapping, prepare_batch
from apps.fatwa_drafts.intake import ReferenceLink, ValidationError, parse_intake, serialize_intake
from apps.fatwa_drafts.domain import transition, RevisionConflict
from apps.reference_links.resolution import Heading, SnapshotCatalog
from tools.content_intake.cli import artifacts


class PipelineTests(unittest.TestCase):
    def row(self, **changes):
        return {'external_id': 'synthetic-1', 'question': '  سؤال تجريبي  ',
                'prepared_clip_url': 'https://example.invalid/finished.mp4', **changes}

    def raw(self, *rows):
        return json.dumps({'schema': 'fatwa.prepared-intake.v1', 'items': list(rows)},
                          ensure_ascii=False).encode()

    def run_batch(self, *rows, **kwargs):
        return prepare_batch(self.raw(*rows), synthetic_fixtures_only=True, **kwargs)

    def mapped(self, **changes):
        values = dict(c2=ReferenceLink('synthetic', 'fake-book', 'fake-edition', 'a'*64, 'b'*64, 'opaque'),
                      edition_id=7, source_row_id=9, test_identity='PipelineTests.test_verified')
        return {C1Pointer('opaque', 'not-a-number'): ExplicitMapping(**(values | changes))}

    def linked(self):
        return self.row(reference_links=[{'source_id': 'opaque', 'heading_id': 'not-a-number'}])

    def catalog(self, namespace='synthetic'):
        return SnapshotCatalog([Heading(7, 9, 'عمل تجريبي', 'عنوان تجريبي', '1', 2,
                                       ('عنوان تجريبي',), namespace, 'fake-book', 'b'*64)])

    def test_c1_acceptance(self):
        outputs, manifest = artifacts(self.raw(self.row()), '.json')
        self.assertEqual(manifest['status'], 'VALID')
        b = prepare_batch(outputs['intake.json'], synthetic_fixtures_only=True)
        self.assertEqual(len(b.drafts), 1)

    def test_c2_compatibility(self):
        b = self.run_batch(self.linked(), reference_map=self.mapped())
        self.assertEqual(parse_intake(serialize_intake((b.drafts[0].intake,)))[0], b.drafts[0].intake)

    def test_no_guessing(self):
        b = self.run_batch(self.linked(), catalog=self.catalog())
        self.assertEqual(b.report['items'][0]['findings'][0]['code'], 'needs_mapping')
        self.assertEqual(b.drafts[0].intake.reference_links, ())

    def test_verified(self):
        b = self.run_batch(self.linked(), reference_map=self.mapped(), catalog=self.catalog())
        self.assertEqual(b.report['items'][0]['references'][0]['outcome'], 'verified')

    def test_not_found(self):
        b = self.run_batch(self.linked(), reference_map=self.mapped(), catalog=SnapshotCatalog([]))
        self.assertEqual(b.report['items'][0]['references'][0]['outcome'], 'not_found')

    def test_mismatch(self):
        b = self.run_batch(self.linked(), reference_map=self.mapped(), catalog=self.catalog('other'))
        self.assertEqual(b.report['items'][0]['references'][0]['outcome'], 'mismatched')

    def test_no_catalog(self):
        b = self.run_batch(self.linked(), reference_map=self.mapped())
        self.assertEqual(b.report['items'][0]['references'][0]['outcome'], 'unverified')

    def test_duplicate_ids_block_both(self):
        b = self.run_batch(self.row(), self.row())
        self.assertEqual(len(b.drafts), 0)
        self.assertEqual(b.report['summary']['blocked-invalid'], 2)

    def test_partial_missing_media(self):
        b = self.run_batch(self.row(), self.row(external_id='synthetic-2', prepared_clip_url=''))
        self.assertEqual(len(b.drafts), 1)
        self.assertEqual(b.report['items'][1]['original']['question'], '  سؤال تجريبي  ')
        self.assertIn('needs-editor-review', b.report['items'][1]['statuses'])

    def test_strict_utf8(self):
        with self.assertRaises(ValidationError):
            prepare_batch(b'\xff', synthetic_fixtures_only=True)

    def test_surrogate(self):
        with self.assertRaises(ValidationError):
            prepare_batch(b'{"schema":"fatwa.prepared-intake.v1","items":["\\ud800"]}', synthetic_fixtures_only=True)

    def test_unknown_field(self):
        self.assertEqual(len(self.run_batch(self.row(approved=True)).drafts), 0)

    def test_payload_cannot_supply_mapping(self):
        self.assertEqual(len(self.run_batch(self.row(reference_map={})).drafts), 0)

    def test_duplicate_json_key(self):
        with self.assertRaises(ValidationError):
            prepare_batch(b'{"schema":1,"schema":2,"items":[]}', synthetic_fixtures_only=True)

    def test_revision_receipt_only(self):
        r = self.run_batch(self.row()).drafts[0]
        self.assertEqual((r.current.number, r.current.action, r.current.answer), (1, 'received', ''))
        self.assertIn('no human editing', r.current.editorial_note)
        moved = transition(r, 'draft_preparation', expected_revision=1,
                           human_editor='synthetic-human', editorial_note='synthetic test')
        self.assertEqual(moved.current.number, 2)
        with self.assertRaises(RevisionConflict):
            transition(moved, 'needs_revision', expected_revision=1,
                       human_editor='synthetic-human', editorial_note='synthetic test')

    def test_exact_original(self):
        b = self.run_batch(self.row())
        self.assertEqual(b.drafts[0].intake.question, self.row()['question'])

    def test_deterministic(self):
        self.assertEqual(self.run_batch(self.row()).json_bytes(), self.run_batch(self.row()).json_bytes())

    def test_no_network_or_django(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('network')), \
             patch.object(sqlite3, 'connect', side_effect=AssertionError('database')), \
             patch.dict(sys.modules, {'django': None, 'psycopg': None}):
            self.assertEqual(len(self.run_batch(self.row()).drafts), 1)

    def test_explicit_synthetic_guard(self):
        with self.assertRaises(ValidationError):
            prepare_batch(self.raw(self.row()))

    def test_invalid_url(self):
        self.assertEqual(len(self.run_batch(self.row(prepared_clip_url='http://example.invalid')).drafts), 0)

    def test_bounds(self):
        for raw in (b'x'*1_000_001, self.raw(*[self.row()]*1001), b'[]'):
            with self.assertRaises(ValidationError):
                prepare_batch(raw, synthetic_fixtures_only=True)

    def test_mapping_positive_exact_integer(self):
        for value in (True, '7', 0):
            with self.assertRaises(ValidationError):
                self.mapped(edition_id=value)

    def test_duplicate_pointer(self):
        row = self.linked()
        row['reference_links'] *= 2
        self.assertEqual(len(self.run_batch(row).drafts), 0)

    def test_preview(self):
        self.assertIn('السؤال الأصلي', self.run_batch(self.row()).preview_ar())

    def test_nonobject_and_bad_id(self):
        b = self.run_batch(None, self.row(external_id=3))
        self.assertEqual(b.report['summary']['blocked-invalid'], 2)

    def test_oversized_pointer_is_row_error(self):
        row = self.row(reference_links=[{'source_id': 'x'*101, 'heading_id': '1'}])
        self.assertEqual(len(self.run_batch(row).drafts), 0)

    def test_exact_pair_required(self):
        mapping = {C1Pointer('opaque', 'different'): next(iter(self.mapped().values()))}
        b = self.run_batch(self.linked(), reference_map=mapping, catalog=self.catalog())
        self.assertEqual(b.report['items'][0]['references'][0]['outcome'], 'unverified')

    def test_ambiguous_preserved(self):
        catalog = self.catalog()
        heading = catalog.lookup(7, 9)[0]
        b = self.run_batch(self.linked(), reference_map=self.mapped(),
                           catalog=SnapshotCatalog([heading, heading]))
        self.assertEqual(b.report['items'][0]['references'][0]['outcome'], 'ambiguous')
