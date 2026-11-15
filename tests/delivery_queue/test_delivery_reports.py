"""Scoped read-only reports must not disclose queue credentials or other cases."""
from datetime import timedelta
from hashlib import sha256
import importlib.util
import json
import os
from unittest.mock import patch

from django.db import connection
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.test import TransactionTestCase, RequestFactory, Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.conf import settings
from django.utils import timezone
from apps.delivery_queue import services as q
from apps.delivery_queue.models import DeliveryAuditEvent
from apps.editorial_workbench.reviewer_access import set_role_cookie


class DeliveryReportTests(TransactionTestCase):
    def setUp(self):
        self.allowed_plan = 'c' * 64
        for case, fingerprint, nonce, receipt in (
            ('allowed-case', self.allowed_plan, 'A' * 40, 'approval-a'),
            ('hidden-case', 'd' * 64, 'B' * 40, 'approval-b')):
            q.commit_approved_plan(receipt_id=receipt, nonce=nonce,
                approval_fingerprint='a' * 64, plan_fingerprint=fingerprint,
                case_key=case, answer_revision=1, provider='reply-source',
                expires_at=timezone.now() + timedelta(minutes=5), parts=((1, 'b' * 64),),
                verify_approval=lambda: True)

    def report_module(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.delivery_queue.reporting'))
        from apps.delivery_queue import reporting
        return reporting

    def test_report_contains_only_assigned_cases(self):
        result = self.report_module().export_scoped_report(case_keys=frozenset({'allowed-case'}))
        text = json.dumps(result)
        self.assertIn('allowed-case', text)
        self.assertNotIn('hidden-case', text)
        self.assertNotIn('approval-b', text)

    def test_report_excludes_tokens_nonces_signatures_and_signed_metadata(self):
        lease = q.claim_next(provider='reply-source', worker_id='report-worker', plan_fingerprint=self.allowed_plan)
        result = self.report_module().export_scoped_report(case_keys=frozenset({'allowed-case'}))
        text = json.dumps(result)
        for forbidden in (lease.token, 'nonce', 'signature', 'token_sha256', 'envelope', 'lease_owner'):
            self.assertNotIn(forbidden, text)

    def test_report_does_not_append_an_audit_event_or_change_state(self):
        before = list(DeliveryAuditEvent.objects.values())
        self.report_module().export_scoped_report(case_keys=frozenset({'allowed-case'}))
        self.assertEqual(list(DeliveryAuditEvent.objects.values()), before)

    def test_report_rejects_unbounded_scope_and_boolean_limit(self):
        module = self.report_module()
        for values in ({'case_keys': frozenset()}, {'case_keys': frozenset({'allowed-case'}), 'limit': True},
                       {'case_keys': frozenset({'allowed-case'}), 'limit': 1001}):
            with self.subTest(values=values), self.assertRaises(q.QueueConflict):
                module.export_scoped_report(**values)

    def test_bounded_pagination_has_an_explicit_continuation(self):
        module = self.report_module()
        scope = frozenset({'allowed-case', 'hidden-case'})
        first = module.export_scoped_report(case_keys=scope, limit=1)
        self.assertTrue(first['has_more'])
        second = module.export_scoped_report(case_keys=scope, limit=1, after=first['next_cursor'])
        self.assertFalse(second['has_more'])
        self.assertNotEqual(first['plans'][0]['case_key'], second['plans'][0]['case_key'])

    def http_module(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.delivery_queue.review_http'))
        from apps.delivery_queue import review_http
        return review_http

    def signed_request(self, method='get', role='operator'):
        request = getattr(RequestFactory(), method)('/review/operator/postgres.json')
        get_token(request)
        response = set_role_cookie(request, HttpResponse(), role)
        request.COOKIES.update({key: value.value for key, value in response.cookies.items()})
        return request

    def test_http_default_off_and_unauthenticated_do_not_query_database(self):
        module = self.http_module()
        with override_settings(FATWA_PG_DELIVERY_REPORTS_ENABLED=False):
            with CaptureQueriesContext(connection) as queries:
                response = module.report_json(RequestFactory().get('/review/operator/postgres.json'))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(len(queries), 0)
        with override_settings(FATWA_PG_DELIVERY_REPORTS_ENABLED=True):
            with CaptureQueriesContext(connection) as queries:
                response = module.report_json(RequestFactory().get('/review/operator/postgres.json'))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(len(queries), 0)

    def test_http_authenticated_operator_receives_no_store_scoped_json_and_head(self):
        module = self.http_module()
        digest = sha256(('1' * 64).encode()).hexdigest()
        with patch.dict(os.environ, {'FATWA_SYNTHETIC_OPERATOR_TOKEN_SHA256': digest}), override_settings(
            FATWA_PG_DELIVERY_REPORTS_ENABLED=True,
            FATWA_PG_DELIVERY_OPERATOR_CASES={'synthetic-operator': ('allowed-case',)}):
            response = module.report_json(self.signed_request())
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertNotIn(b'hidden-case', response.content)
            response = module.report_json(self.signed_request(method='head'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b'')

    def test_http_author_cookie_does_not_grant_operator_permission(self):
        module = self.http_module()
        values = {'FATWA_SYNTHETIC_OPERATOR_TOKEN_SHA256': sha256(b'1' * 64).hexdigest(),
                  'FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256': sha256(b'2' * 64).hexdigest()}
        with patch.dict(os.environ, values), override_settings(FATWA_PG_DELIVERY_REPORTS_ENABLED=True):
            response = module.report_json(self.signed_request(role='author'))
        self.assertEqual(response.status_code, 403)

    def test_http_mutation_is_denied_even_to_an_operator(self):
        module = self.http_module()
        with override_settings(FATWA_PG_DELIVERY_REPORTS_ENABLED=True):
            response = module.report_json(RequestFactory().post('/review/operator/postgres.json'))
        self.assertEqual(response.status_code, 405)
        self.assertIn('no-store', response['Cache-Control'])
