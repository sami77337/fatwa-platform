import hashlib
import json
import unittest

from apps.intake_workflow import contracts as c, fixtures as f


class ContractTests(unittest.TestCase):
    def encode(self, items, **changes):
        return json.dumps({'schema': c.PAYLOAD_SCHEMA, 'synthetic_fixtures_only': True,
                           'items': items, **changes}, ensure_ascii=False).encode()

    def test_acknowledgement_is_literal_and_precedes_parsing(self):
        for value in (False, None, 1, 'true'):
            with self.subTest(value=value), self.assertRaises(c.ContractError):
                c.parse_synthetic_payload(b'not-json', synthetic_fixtures_only=value)

    def test_original_bytes_questions_blocked_and_duplicate_rows_are_retained(self):
        raw = f.synthetic_payload()
        result = c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        self.assertEqual(result.raw, raw)
        self.assertEqual(result.payload_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(result.items[0]['question'], f.ORIGINAL_QUESTION)
        self.assertEqual(len(result.items), 8)
        self.assertEqual(result.items[0]['external_id'], result.items[3]['external_id'])
        self.assertIsNone(result.items[-1])
        self.assertEqual(json.loads(result.prepared_bytes())['items'], list(result.items))

    def test_envelope_ack_unknown_scope_and_config_are_rejected(self):
        for changes in ({'synthetic_fixtures_only': False}, {'scope': c.SYNTHETIC_SCOPE},
                        {'source_config_id': c.SOURCE_CONFIG_ID}, {'schema': 'wrong'}):
            with self.subTest(changes=changes), self.assertRaises(c.ContractError):
                c.parse_synthetic_payload(self.encode([{}], **changes), synthetic_fixtures_only=True)

    def test_exact_bounds_and_individual_bad_rows(self):
        self.assertEqual(len(c.parse_synthetic_payload(self.encode([None] * 1000),
                         synthetic_fixtures_only=True).items), 1000)
        for raw in (b'x' * 1000001, self.encode([]), self.encode([{}] * 1001),
                    self.encode([{'reference_links': [None] * 101}])):
            with self.subTest(size=len(raw)), self.assertRaises(c.ContractError):
                c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)
        c.parse_synthetic_payload(self.encode([{'reference_links': [None] * 100}]),
                                  synthetic_fixtures_only=True)

    def test_duplicate_keys_invalid_unicode_nul_and_nonfinite_fail(self):
        for raw in (b'{"schema":1,"schema":2}', b'\xff', self.encode([{'question': '\x00'}]),
                    b'{"x":"\\ud800"}', self.encode([float('nan')])):
            with self.subTest(raw=raw[:40]), self.assertRaises(c.ContractError):
                c.parse_synthetic_payload(raw, synthetic_fixtures_only=True)

    def test_statuses_are_separate_and_ordinals_start_at_one(self):
        self.assertEqual(c.ROW_ORDINAL_START, 1)
        self.assertEqual(c.REFERENCE_ORDINAL_START, 1)
        self.assertEqual(set(c.IntakeStatus), {'RECEIVED', 'READY_FOR_EDITOR', 'NEEDS_REVIEW', 'BLOCKED_INVALID'})
        self.assertEqual(set(c.ReferenceStatus), {'VERIFIED', 'UNVERIFIED', 'MISMATCHED'})
        self.assertEqual(set(c.ReviewStatus), {'UNREVIEWED', 'IN_REVIEW', 'NEEDS_CHANGES', 'REVIEWED_INTERNAL'})

    def test_idempotency_decisions_and_409_conflict(self):
        pin = 'a' * 64
        self.assertEqual(c.idempotency_decision(None, pin), c.IdempotencyDecision.CREATE)
        self.assertEqual(c.idempotency_decision(pin, pin), c.IdempotencyDecision.REPLAY)
        with self.assertRaises(c.IdempotencyConflict) as caught:
            c.idempotency_decision(pin, 'b' * 64)
        self.assertEqual((caught.exception.code, caught.exception.status_code), ('IDEMPOTENCY_CONFLICT', 409))
        for invalid in ('', 'A' * 64, 'x' * 64):
            with self.assertRaises(c.ContractError):
                c.idempotency_decision(None, invalid)

    def test_transition_graph_has_no_publication_or_answer_action(self):
        state = c.next_review_status('UNREVIEWED', 'start_review')
        self.assertEqual(state, 'IN_REVIEW')
        self.assertEqual(c.next_review_status(state, 'request_changes'), 'NEEDS_CHANGES')
        self.assertEqual(c.next_review_status('NEEDS_CHANGES', 'start_review'), 'IN_REVIEW')
        self.assertEqual(c.next_review_status(state, 'complete_review'), 'REVIEWED_INTERNAL')
        for state, action in [('UNREVIEWED', 'complete_review'), ('REVIEWED_INTERNAL', 'start_review'),
                              ('IN_REVIEW', 'publish'), ('IN_REVIEW', 'approve_fatwa')]:
            with self.assertRaises(c.ContractError):
                c.next_review_status(state, action)

    def test_fixed_reference_identity_cannot_be_inferred_or_weakened(self):
        self.assertEqual(len(c.VERIFIED_IDENTITIES), 3)
        self.assertEqual(c.validate_verified_identity(dict(c.VERIFIED_IDENTITIES[0])), dict(c.VERIFIED_IDENTITIES[0]))
        for changes in ({'source_archive_sha256': 'c' * 64}, {'edition_id': '7001'},
                        {'source_row_id': True}, {'source_id': 'guessed'}, {'extra': 'x'}):
            value = dict(c.VERIFIED_IDENTITIES[0]) | changes
            with self.subTest(changes=changes), self.assertRaises(c.ContractError):
                c.validate_verified_identity(value)

    def test_external_id_validity_keeps_original_and_blocks_controls(self):
        self.assertEqual(c.valid_external_id('OPAQUE/ROW-1'), 'OPAQUE/ROW-1')
        for value in (None, 4, '', ' padded ', 'x\t', 'x\n', 'x\x7f', 'x' * 101):
            with self.subTest(value=value):
                self.assertIsNone(c.valid_external_id(value))

    def test_database_edge_whitespace_matches_python313_id_contract(self):
        expected = ''.join(chr(code) for code in range(0x110000) if chr(code).isspace())
        self.assertEqual(c.EXTERNAL_ID_EDGE_WHITESPACE,expected)
