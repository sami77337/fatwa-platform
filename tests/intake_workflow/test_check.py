"""Pure source-preserving intake checks; no Django/database setup required."""
import hashlib
import json
import sys
import unittest
from unittest.mock import patch

from apps.intake_workflow import contracts as c, fixtures as f
from apps.intake_workflow.intake import check_intake


def payload(rows):
    return json.dumps(dict(schema=c.PAYLOAD_SCHEMA, synthetic_fixtures_only=True, items=rows),
                      ensure_ascii=False, separators=(',', ':')).encode()


def valid_row(**changes):
    return dict(external_id='SYN UNSEEN', question='  سُؤَالٌ\t\r\n  ',
                staff_notes=' \tمُلاحظة\n ', prepared_clip_url='https://example.invalid/clip.mp4') | changes


class CheckTests(unittest.TestCase):
    def test_fixed_fixture_keeps_all_ordinals_duplicates_and_readiness(self):
        checked = check_intake(f.synthetic_payload(), synthetic_fixtures_only=True)
        self.assertEqual(len(checked.items), 8)
        self.assertEqual([i.row_ordinal for i in checked.items], list(range(1, 9)))
        self.assertEqual([i.intake_status for i in checked.items],
                         ['BLOCKED_INVALID', 'NEEDS_REVIEW', 'BLOCKED_INVALID', 'BLOCKED_INVALID',
                          'BLOCKED_INVALID', 'BLOCKED_INVALID', 'READY_FOR_EDITOR', 'BLOCKED_INVALID'])
        self.assertEqual(checked.items[0].question_original, f.ORIGINAL_QUESTION)
        self.assertEqual(checked.items[0].external_id, checked.items[3].external_id)
        self.assertEqual(checked.items[7].source.text, 'null')
        self.assertEqual(checked.report()['item_count'], 8)
        self.assertNotIn(f.ORIGINAL_QUESTION, json.dumps(checked.report(), ensure_ascii=False))

    def test_source_slices_and_validation_do_not_rewrite_numbers_or_original_text(self):
        digits = b'9' * 6000
        raw = (b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
               b'{"external_id":73.000000000000001,"question":"  A\\t\\r\\n  ",'
               b'"reference_links":[ {"source_id":73.000000000000001},null,1e-20000 ]},'
               + digits + b',1e-999999999999999999999999999, null]}')
        checked = check_intake(raw, synthetic_fixtures_only=True)
        self.assertEqual(len(checked.items), 4)
        self.assertTrue(all(i.intake_status == 'BLOCKED_INVALID' for i in checked.items))
        self.assertTrue(all(i.external_id is None for i in checked.items))
        self.assertEqual(checked.items[0].question_original, '  A\t\r\n  ')
        self.assertEqual(checked.parsed.raw, raw)
        self.assertEqual(checked.parsed.payload_sha256, hashlib.sha256(raw).hexdigest())
        self.assertIn(b'73.000000000000001', checked.parsed.prepared_bytes())
        for item in checked.items:
            self.assertEqual(raw[item.source.start:item.source.end], item.source.text.encode())
            for source in item.references:
                self.assertEqual(raw[source.start:source.end], source.text.encode())
        self.assertEqual([s.text for s in checked.items[0].references],
                         ['{"source_id":73.000000000000001}', 'null', '1e-20000'])

    def test_string_ids_and_questions_notes_keep_whitespace_controls_are_blocked(self):
        ids = ['SYN UNSEEN', 'SYN\tUNSEEN', 'SYN\x85UNSEEN', 'SYN\x7fUNSEEN', 73]
        checked = check_intake(payload([valid_row(external_id=i) for i in ids]), synthetic_fixtures_only=True)
        self.assertEqual([i.external_id for i in checked.items], ['SYN UNSEEN', None, None, None, None])
        self.assertEqual(checked.items[0].intake_status, 'READY_FOR_EDITOR')
        self.assertTrue(all(i.intake_status == 'BLOCKED_INVALID' for i in checked.items[1:]))
        self.assertEqual(checked.items[0].question_original, valid_row()['question'])

    def test_invalid_reference_types_and_duplicate_rows_stay_present(self):
        rows = [None, 73, [None], valid_row(reference_links=[None, 73, {'x': 1}]),
                valid_row(reference_links='[]'), valid_row()]
        checked = check_intake(payload(rows), synthetic_fixtures_only=True)
        self.assertEqual(len(checked.items), len(rows))
        self.assertEqual(len(checked.items[3].references), 3)
        self.assertEqual(checked.items[4].references, ())
        self.assertTrue(all(i.intake_status == 'BLOCKED_INVALID' for i in checked.items))

    def test_bounds_reject_before_partial_report_and_allow_exact_row_reference_maxima(self):
        for raw in (b'x' * 1_000_001, payload([None] * 1001),
                    payload([valid_row(reference_links=[None] * 101)])):
            with self.subTest(size=len(raw)), self.assertRaises(c.ContractError):
                check_intake(raw, synthetic_fixtures_only=True)
        self.assertEqual(len(check_intake(payload([None] * 1000), synthetic_fixtures_only=True).items), 1000)
        checked = check_intake(payload([valid_row(reference_links=[None] * 100)]), synthetic_fixtures_only=True)
        self.assertEqual(len(checked.items[0].references), 100)

    def test_exact_million_byte_numeric_row_is_retained_without_digit_setting_changes(self):
        prefix = b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
        raw = prefix + b'9' * (1_000_000 - len(prefix) - 2) + b']}'
        limit = sys.get_int_max_str_digits()
        checked = check_intake(raw, synthetic_fixtures_only=True)
        self.assertEqual(len(raw), 1_000_000)
        self.assertEqual(checked.items[0].source.text.encode(), raw[len(prefix):-2])
        self.assertEqual(checked.items[0].intake_status, 'BLOCKED_INVALID')
        self.assertEqual(sys.get_int_max_str_digits(), limit)

    def test_bad_envelopes_duplicate_keys_unicode_and_untrusted_configuration_reject(self):
        for raw in (b'[]', b'\xff', b'{"schema":1,"schema":2}',
                    payload([valid_row(question='\x00')]), b'"\\ud800"',
                    payload([valid_row()]).replace(b'"items":', b'"scope":"untrusted","items":')):
            with self.subTest(raw=raw[:40]), self.assertRaises(c.ContractError):
                check_intake(raw, synthetic_fixtures_only=True)
        checked = check_intake(payload([valid_row(reference_map={})]), synthetic_fixtures_only=True)
        self.assertEqual(checked.items[0].intake_status, 'BLOCKED_INVALID')

    def test_acknowledgement_before_processing_and_no_database_network_import(self):
        for ack in (False, 1, None):
            with self.assertRaises(c.ContractError):
                check_intake(b'not-json', synthetic_fixtures_only=ack)
        with patch.dict(sys.modules, {'django': None, 'psycopg': None}), \
             patch('socket.socket', side_effect=AssertionError('network')):
            self.assertEqual(check_intake(payload([valid_row()]), synthetic_fixtures_only=True).items[0].intake_status,
                             'READY_FOR_EDITOR')
