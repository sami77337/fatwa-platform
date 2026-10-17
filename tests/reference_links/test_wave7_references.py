"""Wave7 reference plans are pure and preserve approved lossless source slices."""
import hashlib
import json
import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from apps.intake_workflow import contracts as c, fixtures as f
from apps.reference_links.resolution import Heading


def catalog_rows():
    root = 'كِتَابٌ اصطناعي'
    return tuple(Heading(7001, row, 'مرجع اصطناعي لتجارب Wave7', title, 'الأول', 6 + row,
                         (root,) if row == 1 else (root, title),
                         c.SOURCE_IDENTITY['source_namespace'], '622', 'b' * 64,
                         c.SOURCE_IDENTITY['edition_key'], 'a' * 64)
                 for row, title in ((1, root), (2, 'بابٌ اصطناعي أول'), (3, 'بابٌ اصطناعي ثان')))


def raw_items(items):
    return json.dumps({'schema': c.PAYLOAD_SCHEMA, 'synthetic_fixtures_only': True,
                       'items': items}, ensure_ascii=False, separators=(',', ':')).encode()


def c1(row=1):
    return {'source_id': 'W7-SOURCE', 'heading_id': f'W7-HEADING-{row}'}


class Wave7ReferencePlans(unittest.TestCase):
    def plan(self, raw=None, rows=None):
        from apps.intake_workflow.references import plan_reference_verification
        return plan_reference_verification(raw or raw_items([{'reference_links': [c1()]}]),
            synthetic_fixtures_only=True, catalog_rows=catalog_rows() if rows is None else rows)

    def test_acknowledgement_is_required_before_processing(self):
        from apps.intake_workflow.references import plan_reference_verification
        for ack in (False, 1, None):
            with self.subTest(ack=ack), self.assertRaises(c.ContractError):
                plan_reference_verification(object(), synthetic_fixtures_only=ack)

    def test_c1_full_path_and_exact_source(self):
        raw = raw_items([{'reference_links': [c1(2)]}])
        result = self.plan(raw)[0].references[0]
        self.assertEqual(result.status, c.ReferenceStatus.VERIFIED)
        self.assertEqual(result.evidence.path, ('كِتَابٌ اصطناعي', 'بابٌ اصطناعي أول'))
        self.assertEqual(raw[result.source.start:result.source.end], result.source.text.encode())
        self.assertEqual(result.derived_values()['verified_identity'], dict(c.VERIFIED_IDENTITIES[1]))
        self.assertIn('ج الأول، ص 8', result.citation_text)
        self.assertIn('وليس نص فتوى', result.citation_text)

    def test_c2_all_six_fields_are_exact_and_required(self):
        pointer = {**c.SOURCE_IDENTITY, 'source_id': 'wave7-title-3'}
        self.assertEqual(self.plan(raw_items([{'reference_links': [pointer]}]))[0].references[0].status,
                         c.ReferenceStatus.VERIFIED)
        for key in pointer:
            altered = dict(pointer, **{key: 'wrong'})
            result = self.plan(raw_items([{'reference_links': [altered]}]))[0].references[0]
            self.assertEqual(result.status, c.ReferenceStatus.MISMATCHED)
            self.assertEqual(result.citation_text, '')
            missing = {k: v for k, v in pointer.items() if k != key}
            self.assertEqual(self.plan(raw_items([{'reference_links': [missing]}]))[0].references[0].status,
                             c.ReferenceStatus.UNVERIFIED)

    def test_no_numeric_coercion_question_inference_or_extra_fields(self):
        pointers = [{'source_id': '7001', 'heading_id': '1'},
                    {'source_id': 'W7-SOURCE', 'heading_id': 1},
                    {**c1(), 'edition_id': 7001}, None, 73, [1], {'source_id': True}]
        result = self.plan(raw_items([{'question': 'W7-HEADING-1', 'reference_links': pointers}]))
        self.assertTrue(all(r.status == c.ReferenceStatus.UNVERIFIED for r in result[0].references))
        for reference in result[0].references:
            values = reference.derived_values()
            self.assertEqual(values['verified_identity'], {})
            self.assertEqual(values['citation_text'], '')

    def test_missing_or_ambiguous_catalog_has_no_citation(self):
        for rows in ((), (catalog_rows()[0], catalog_rows()[0])):
            result = self.plan(rows=rows)[0].references[0]
            self.assertEqual(result.status, c.ReferenceStatus.UNVERIFIED)
            self.assertIsNone(result.evidence)
            self.assertEqual(result.citation_text, '')

    def test_every_catalog_field_and_full_path_must_match(self):
        row = catalog_rows()[1]
        changes = ({'edition_key': 'wrong'}, {'source_archive_sha256': 'c' * 64},
                   {'source_input_sha256': 'c' * 64}, {'source_namespace': 'wrong'},
                   {'source_book_id': 'wrong'}, {'work_title': '<script>wrong</script>'},
                   {'heading_title': 'wrong', 'path': ('wrong',)},
                   {'path': (row.heading_title,)}, {'printed_part': 'الثاني'}, {'printed_page': 99})
        raw = raw_items([{'reference_links': [c1(2)]}])
        for values in changes:
            with self.subTest(values=values):
                result = self.plan(raw, rows=(replace(row, **values),))[0].references[0]
                self.assertEqual(result.status, c.ReferenceStatus.MISMATCHED)
                self.assertIsNone(result.evidence)
                self.assertEqual(result.citation_text, '')

    def test_optional_legacy_heading_pins_need_complete_fixed_configuration(self):
        legacy = replace(catalog_rows()[0], edition_key=None, source_archive_sha256=None)
        self.assertEqual(self.plan(rows=(legacy,))[0].references[0].status, c.ReferenceStatus.VERIFIED)
        with patch.object(f, 'trusted_reference_map', return_value={}):
            result = self.plan(rows=(legacy,))[0].references[0]
        self.assertEqual(result.status, c.ReferenceStatus.UNVERIFIED)
        self.assertEqual(result.citation_text, '')
        # Compatibility for absent optional pins requires the complete fixed
        # configuration, even if this particular pointer has a surviving map.
        partial = dict(list(f.trusted_reference_map().items())[:1])
        with patch.object(f, 'trusted_reference_map', return_value=partial):
            result = self.plan(rows=(legacy,))[0].references[0]
        self.assertEqual(result.status, c.ReferenceStatus.UNVERIFIED)
        self.assertEqual(result.citation_text, '')

    def test_duplicate_pointers_retain_distinct_original_byte_slices(self):
        raw = ('{"schema":"'+c.PAYLOAD_SCHEMA+'","synthetic_fixtures_only":true,"items":['
               '{"reference_links":[{ "source_id":"W7-SOURCE", "heading_id":"W7-HEADING-1" },'
               '{"heading_id":"W7-HEADING-1","source_id":"W7-SOURCE"}]}]}').encode()
        refs = self.plan(raw)[0].references
        self.assertEqual(len(refs), 2)
        self.assertTrue(all(r.reasons == ('duplicate_pointer',) for r in refs))
        self.assertNotEqual(refs[0].source, refs[1].source)
        for ref in refs:
            self.assertEqual(raw[ref.source.start:ref.source.end], ref.source.text.encode())

    def test_lossless_numbers_and_invalid_rows_are_not_reserialized(self):
        prefix = ('{"schema":"'+c.PAYLOAD_SCHEMA+'","synthetic_fixtures_only":true,"items":[').encode()
        raw = prefix + (b'{"external_id":73.000000000000001,"question":"  q\\t\\n  ",'
                        b'"reference_links":[ {"source_id":73.000000000000001},1e-20000,null,'
                        b'1e-999999999999999999999999,') + b'9' * 6000 + b']},null,73.000000000000001]}'
        results = self.plan(raw)
        self.assertEqual(len(results), 3)
        self.assertEqual([len(r.references) for r in results], [5, 0, 0])
        for ref in results[0].references:
            self.assertEqual(ref.status, c.ReferenceStatus.UNVERIFIED)
            self.assertEqual(raw[ref.source.start:ref.source.end], ref.source.text.encode())
            self.assertEqual(ref.derived_values()['verification_results']['source']['text'], ref.source.text)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), c.parse_synthetic_payload(
            raw, synthetic_fixtures_only=True).payload_sha256)

    def test_intake_readiness_and_duplicate_external_ids_do_not_determine_reference_evidence(self):
        rows = [{'external_id': 'BAD\tID', 'reference_links': [c1()]},
                {'external_id': 'DUP', 'reference_links': [c1(2)]},
                {'external_id': 'DUP', 'reference_links': [c1(3)]}, None]
        result = self.plan(raw_items(rows))
        self.assertEqual([r.row_ordinal for r in result], [1, 2, 3, 4])
        self.assertTrue(all(r.references[0].status == c.ReferenceStatus.VERIFIED for r in result[:3]))
        self.assertEqual(result[-1].references, ())

    def test_derived_update_whitelist_and_no_io(self):
        with patch('socket.socket', side_effect=AssertionError('network')), \
             patch('builtins.open', side_effect=AssertionError('source read')):
            ref = self.plan()[0].references[0]
        self.assertEqual(set(ref.derived_values()), {'reference_status', 'verification_results',
                         'verified_identity', 'citation_text'})

    def test_derived_json_representation_is_stable_for_replay(self):
        values = self.plan()[0].references[0].derived_values()
        self.assertEqual(json.loads(json.dumps(values, allow_nan=False)), values)

    def test_bad_envelopes_bounds_and_unicode_are_rejected(self):
        for raw in (b'[]', b'\xff', b' ' * 1000001,
                    raw_items([{'reference_links': [c1()] * 101}]),
                    b'{"schema":"x","schema":"y"}',
                    ('{"schema":"'+c.PAYLOAD_SCHEMA+'","synthetic_fixtures_only":true,'
                     '"items":["\\ud800"]}').encode()):
            with self.subTest(size=len(raw)), self.assertRaises(c.ContractError):
                self.plan(raw)

    def test_write_entrypoint_denies_before_model_registry_or_transaction(self):
        from apps.intake_workflow.references import verify_batch_references
        from apps.intake_workflow.guards import SyntheticWriteDenied
        for ack in (False, 1):
            with self.subTest(ack=ack), self.assertRaises(c.ContractError):
                verify_batch_references(uuid4(), synthetic_fixtures_only=ack)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SyntheticWriteDenied, 'WRITES_DISABLED'):
                verify_batch_references(uuid4(), synthetic_fixtures_only=True)

    def test_source_preflight_rejects_text_or_offset_tampering(self):
        from apps.intake_workflow.references import _check_source
        source = c.parse_synthetic_payload(raw_items([{'reference_links': [c1()]}]),
                                          synthetic_fixtures_only=True).reference_sources[0][0]
        ref = SimpleNamespace(original_pointer=source.text, source_byte_start=source.start,
                              source_byte_end=source.end)
        _check_source(ref, source, 'original_pointer')
        for changes in ({'original_pointer': source.text + ' '},
                        {'source_byte_start': source.start + 1}, {'source_byte_end': source.end + 1}):
            with self.subTest(changes=changes), self.assertRaises(c.ContractError):
                _check_source(SimpleNamespace(**(vars(ref) | changes)), source, 'original_pointer')

    def test_extreme_exponent_uses_source_token_without_decimal_arithmetic(self):
        token = b'1e-' + b'9' * 6000
        raw = (b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
               b'"items":[{"reference_links":[' + token + b']}]}')
        ref = self.plan(raw)[0].references[0]
        self.assertEqual(ref.source.text.encode(), token)
        self.assertEqual(ref.status, c.ReferenceStatus.UNVERIFIED)

    def test_actual_catalog_projection_checks_ancestor_ids_not_just_titles(self):
        from apps.intake_workflow.references import _catalog_projection_conflicts
        correct = ((1, 'wave7-title-1', None, None, None, 1),
                   (2, 'wave7-title-2', 1, 7001, 'wave7-title-1', 2))
        self.assertEqual(_catalog_projection_conflicts(correct), frozenset())
        for bad in ((2, 'wave7-title-2', 99, 7001, 'unmapped-parent', 2),
                    (2, 'wave7-title-2', 1, 7002, 'wave7-title-1', 2),
                    (2, 'opaque-wrong', 1, 7001, 'wave7-title-1', 2),
                    (2, 'wave7-title-2', 1, 7001, 'wrong-parent', 2)):
            self.assertEqual(_catalog_projection_conflicts((correct[0], bad)), frozenset({2}))
