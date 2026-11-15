"""Real authenticated author requests with CSRF and fixed server trust settings."""
from hashlib import sha256
from html import unescape
import importlib.util
import os
import re
from unittest.mock import patch
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from tests.delivery_queue.author_desk_fixtures import JournalFixture

BASE = '/review/author/approval/'
LOGIN = '/review/author/approval/login/'


class AuthorDeskHttpTests(TransactionTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.delivery_queue.author_http'), 'author_http must exist')
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()
        self.token = 'a' * 64
        env = patch.dict(os.environ, {'FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256': sha256(self.token.encode()).hexdigest()})
        env.start()
        self.addCleanup(env.stop)
        config = override_settings(ROOT_URLCONF='apps.delivery_queue.author_urls',
            ALLOWED_HOSTS=['testserver', '127.0.0.1'],
            MIDDLEWARE=['apps.delivery_queue.author_http.AuthorDeskGuard',
                        'django.middleware.csrf.CsrfViewMiddleware'],
            CSRF_COOKIE_NAME='fatwa_training_desk_csrf', CSRF_COOKIE_PATH='/review/',
            CSRF_COOKIE_HTTPONLY=True, CSRF_COOKIE_SECURE=False, CSRF_COOKIE_SAMESITE='Strict',
            FATWA_AUTHOR_APPROVAL_ENABLED=True,
            FATWA_AUTHOR_APPROVAL_DIRECTORY=self.fixture.directory,
            FATWA_AUTHOR_APPROVAL_CASES=(CASE_KEY,), FATWA_AUTHOR_APPROVAL_MAX_CHARS=32,
            FATWA_AUTHOR_APPROVAL_VERIFIER=self.fixture.verifier)
        config.enable()
        self.addCleanup(config.disable)
        self.client = Client(enforce_csrf_checks=True)

    def hidden(self, response, name):
        found = re.search(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', response.content.decode())
        self.assertIsNotNone(found, name)
        return unescape(found.group(1))

    def login(self):
        form = self.client.get(LOGIN)
        self.assertEqual(form.status_code, 200)
        response = self.client.post(LOGIN, {'token': self.token,
            'csrfmiddlewaretoken': self.hidden(form, 'csrfmiddlewaretoken')})
        self.assertEqual(response.status_code, 303)

    def page_and_request(self):
        self.login()
        page = self.client.get(BASE + '?split=1')
        self.assertEqual(page.status_code, 200)
        export = self.client.get(BASE + 'request.json?split=1')
        self.assertEqual(export.status_code, 200)
        return page, export.json()

    def stage_fields(self, page, request):
        return {'csrfmiddlewaretoken': self.hidden(page, 'csrfmiddlewaretoken'),
            'request_sha256': self.hidden(page, 'request_sha256'),
            'confirmation': self.hidden(page, 'confirmation'), 'split': '1', 'acknowledge': '1',
            'response': self.fixture.signed_response(request)}

    def test_disabled_and_unauthenticated_routes_do_not_query_database(self):
        with override_settings(FATWA_AUTHOR_APPROVAL_ENABLED=False), CaptureQueriesContext(connection) as queries:
            response = self.client.get(BASE)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(queries), 0)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(BASE)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(queries), 0)

    def test_read_only_preview_export_and_head_preserve_journal(self):
        before = self.fixture.files()
        page, request = self.page_and_request()
        self.assertIn('no-store', page['Cache-Control'])
        self.assertEqual(self.client.head(BASE + 'request.json?split=1').content, b'')
        self.assertEqual(request['status'], 'REQUEST_NOT_APPROVED')
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(self.fixture.files(), before)

    def test_native_signed_receipt_import_is_idempotent_and_not_delivery(self):
        page, request = self.page_and_request()
        fields = self.stage_fields(page, request)
        for _ in range(2):
            response = self.client.post(BASE + 'receipt/', fields)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertIn('STAGED_NOT_SENT', response.content.decode())
        self.assertEqual(ApprovalClaim.objects.count(), 1)
        self.assertEqual(DeliveryIntent.objects.count(), len(request['segments']))

    def test_csrf_and_acknowledgement_cannot_be_omitted(self):
        page, request = self.page_and_request()
        fields = self.stage_fields(page, request)
        without_csrf = dict(fields)
        without_csrf.pop('csrfmiddlewaretoken')
        self.assertEqual(self.client.post(BASE + 'receipt/', without_csrf).status_code, 403)
        fields.pop('acknowledge')
        self.assertEqual(self.client.post(BASE + 'receipt/', fields).status_code, 400)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_wrong_browser_confirmation_blocks_valid_signature(self):
        page, request = self.page_and_request()
        fields = self.stage_fields(page, request)
        fields['confirmation'] = '0' * 64
        self.assertEqual(self.client.post(BASE + 'receipt/', fields).status_code, 403)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_stale_page_is_not_silently_rebuilt_and_approved(self):
        page, request = self.page_and_request()
        fields = self.stage_fields(page, request)
        self.fixture.correct_source()
        self.assertEqual(self.client.post(BASE + 'receipt/', fields).status_code, 409)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_missing_trusted_verifier_cannot_fall_back_to_test_callback(self):
        page, request = self.page_and_request()
        fields = self.stage_fields(page, request)
        with override_settings(FATWA_AUTHOR_APPROVAL_VERIFIER=None):
            self.assertEqual(self.client.post(BASE + 'receipt/', fields).status_code, 503)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_server_case_scope_is_not_taken_from_url(self):
        self.login()
        with override_settings(FATWA_AUTHOR_APPROVAL_CASES=('different-case',)):
            self.assertEqual(self.client.get(BASE).status_code, 403)
        self.assertEqual(self.client.get(BASE + '?directory=/tmp').status_code, 400)

    def test_state_changing_get_and_non_loopback_requests_are_rejected(self):
        self.login()
        self.assertEqual(self.client.get(BASE + 'receipt/').status_code, 405)
        self.assertEqual(self.client.get(BASE, REMOTE_ADDR='198.51.100.1').status_code, 403)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_role_cookie_alone_in_another_browser_is_insufficient(self):
        self.login()
        other = Client(enforce_csrf_checks=True)
        other.cookies['fatwa_training_author'] = self.client.cookies['fatwa_training_author']
        self.assertEqual(other.get(BASE).status_code, 403)

    def test_errors_do_not_echo_signed_receipt_or_raw_exception(self):
        page, request = self.page_and_request()
        fields = self.stage_fields(page, request)
        fields['response'] = '{"secret":"do-not-echo-this"}'
        response = self.client.post(BASE + 'receipt/', fields)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b'do-not-echo-this', response.content)
        self.assertNotIn(b'Traceback', response.content)
