"""Service acceptance: existing journal -> external signature -> PostgreSQL."""
import importlib
import importlib.util
import json
import os
from unittest.mock import patch
from django.test import TransactionTestCase
from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent, DeliveryAttempt
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from tests.delivery_queue.author_desk_fixtures import JournalFixture, BODY


class AuthorHandoffTests(TransactionTestCase):
    def setUp(self):
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.delivery_queue.author_handoff'), 'author_handoff must exist')
        return importlib.import_module('apps.delivery_queue.author_handoff')

    def request(self, split=True):
        return self.api().build_approval_request(self.fixture.directory, case_key=CASE_KEY,
            max_chars=32, split=split, synthetic_fixtures_only=True)

    def stage(self, response, **changes):
        values = dict(directory=self.fixture.directory, case_key=CASE_KEY, max_chars=32, split=True,
            response_json=response, verifier=self.fixture.verifier, synthetic_fixtures_only=True)
        values.update(changes)
        return self.api().stage_signed_response(**values)

    def test_export_is_deterministic_lossless_and_does_not_create_claims(self):
        before = self.fixture.files()
        request = self.request()
        self.assertEqual(self.request(), request)
        self.assertEqual(request['answer']['body'], BODY)
        self.assertEqual(''.join(part['exact_text'] for part in request['segments']), BODY)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(self.fixture.files(), before)

    def test_export_is_request_only_not_a_mufti_receipt(self):
        request = self.request()
        self.assertEqual(request['status'], 'REQUEST_NOT_APPROVED')
        self.assertNotIn('signature_b64url', json.dumps(request))
        self.assertNotIn('approver_id', json.dumps(request))

    def test_split_choice_is_required(self):
        self.api()
        with self.assertRaises(ValueError):
            self.request(split=False)

    def test_signed_response_stages_all_parts_once_without_sending(self):
        request = self.request()
        response = self.fixture.signed_response(request)
        before = self.fixture.files()
        first = self.stage(response)
        second = self.stage(response)
        self.assertEqual(first, second)
        self.assertEqual(ApprovalClaim.objects.count(), 1)
        self.assertEqual(DeliveryIntent.objects.count(), len(request['segments']))
        self.assertEqual(set(DeliveryIntent.objects.values_list('state', flat=True)), {'STAGED'})
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        self.assertEqual(self.fixture.files(), before)

    def test_source_change_invalidates_old_request(self):
        response = self.fixture.signed_response(self.request())
        self.fixture.correct_source()
        with self.assertRaises(ValueError):
            self.stage(response)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_new_confirmed_draft_invalidates_old_request(self):
        response = self.fixture.signed_response(self.request())
        self.fixture.draft(body=BODY + 'تعديل')
        self.fixture.note('submit')
        self.fixture.note('confirm')
        with self.assertRaises(ValueError):
            self.stage(response)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_open_clarification_blocks_handoff(self):
        response = self.fixture.signed_response(self.request())
        self.fixture.request_clarification()
        with self.assertRaises(ValueError):
            self.stage(response)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_revoked_signature_cannot_be_staged(self):
        response = self.fixture.signed_response(self.request())
        self.fixture.revoked = True
        with self.assertRaises(ValueError):
            self.stage(response)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_receipt_for_other_case_and_wrong_request_hash_are_rejected(self):
        request = self.request()
        other = self.fixture.signed_response(request, case_key='another-case')
        with self.assertRaises(ValueError):
            self.stage(other)
        altered = json.loads(self.fixture.signed_response(request))
        altered['request_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.stage(json.dumps(altered))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_duplicate_unknown_and_wrongly_typed_json_fields_fail_closed(self):
        request = self.request()
        response = self.fixture.signed_response(request)
        record = json.loads(response)
        cases = ['{"request_sha256":"a","request_sha256":"b","receipt":{}}',
                 response[:-1] + ',"issuer":"attacker"}', '[' + response + ']', 'x' * 17000]
        record['receipt']['answer_revision'] = True
        cases.append(json.dumps(record))
        for value in cases:
            with self.subTest(value=value[:60]), self.assertRaises(ValueError):
                self.stage(value)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_server_verifier_cannot_be_replaced_with_boolean_callback(self):
        response = self.fixture.signed_response(self.request())
        with self.assertRaises(ValueError):
            self.stage(response, verifier=lambda value: True)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_wrong_case_and_disabled_mode_have_no_side_effect(self):
        self.api()
        before = self.fixture.files()
        with self.assertRaises(ValueError):
            self.api().build_approval_request(self.fixture.directory, case_key='another', max_chars=32,
                split=True, synthetic_fixtures_only=True)
        with patch.dict(os.environ, {'FATWA_PRODUCTION': '1'}), self.assertRaises(ValueError):
            self.request()
        self.assertEqual(self.fixture.files(), before)
