"""Browser-bound forms and role separation for the combined review desk."""
from dataclasses import replace
from hashlib import sha256
from html import unescape
import importlib.util
import os
import re
from unittest.mock import patch
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from apps.delivery_queue.models import ApprovalClaim, DeliveryAttempt
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from tests.delivery_queue.author_desk_fixtures import JournalFixture
from tests.delivery_queue.test_author_desk_http import NativeFormClient

AUTHOR_BASE = '/review/author/approval/'
MUFTI_BASE = '/review/mufti/decisions/'
MUFTI_LOGIN = '/review/mufti/login/'


class MuftiDeskHttpTests(TransactionTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.mufti_review.views'), 'Mufti desk must be implemented')
        from tests.mufti_review.provider_fixture import FixtureDirectory
        self.directory = FixtureDirectory()
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()
        env = patch.dict(os.environ, {'FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256': sha256(b'a' * 64).hexdigest()})
        env.start()
        self.addCleanup(env.stop)
        config = override_settings(ROOT_URLCONF='apps.mufti_review.urls',
            ALLOWED_HOSTS=['testserver', '127.0.0.1'],
            MIDDLEWARE=['apps.mufti_review.views.ReviewDeskGuard', 'django.middleware.csrf.CsrfViewMiddleware'],
            CSRF_COOKIE_NAME='fatwa_training_desk_csrf', CSRF_COOKIE_PATH='/review/',
            CSRF_COOKIE_HTTPONLY=True, CSRF_COOKIE_SECURE=False, CSRF_COOKIE_SAMESITE='Strict',
            FATWA_MUFTI_REVIEW_ENABLED=True, FATWA_MUFTI_IDENTITY_PROVIDER=self.directory,
            FATWA_AUTHOR_APPROVAL_ENABLED=True, FATWA_AUTHOR_APPROVAL_DIRECTORY=self.fixture.directory,
            FATWA_AUTHOR_APPROVAL_CASES=(CASE_KEY,), FATWA_AUTHOR_APPROVAL_MAX_CHARS=32,
            FATWA_AUTHOR_APPROVAL_VERIFIER=self.fixture.verifier)
        config.enable()
        self.addCleanup(config.disable)
        self.author = NativeFormClient(enforce_csrf_checks=True)
        self.mufti = NativeFormClient(enforce_csrf_checks=True)

    def hidden(self, response, field):
        match = re.search(r'name="' + re.escape(field) + r'"[^>]*value="([^"]*)"', response.content.decode())
        self.assertIsNotNone(match, (field, response.status_code, response.content[:100]))
        return unescape(match.group(1))

    def login_author(self):
        form = self.author.get(AUTHOR_BASE + 'login/')
        response = self.author.post(AUTHOR_BASE + 'login/', {'token': 'a' * 64,
            'csrfmiddlewaretoken': self.hidden(form, 'csrfmiddlewaretoken')})
        self.assertEqual(response.status_code, 303, response.content)

    def login_mufti(self):
        form = self.mufti.get(MUFTI_LOGIN)
        response = self.mufti.post(MUFTI_LOGIN, {'credential': 'M' * 64,
            'csrfmiddlewaretoken': self.hidden(form, 'csrfmiddlewaretoken')})
        self.assertEqual(response.status_code, 303, response.content)

    def submit(self):
        self.login_author()
        page = self.author.get(AUTHOR_BASE + '?split=1')
        fields = {key: self.hidden(page, key) for key in ('csrfmiddlewaretoken', 'request_sha256', 'confirmation')}
        fields.update(split='1', acknowledge='1')
        result = self.author.post(AUTHOR_BASE + 'review/', fields)
        self.assertEqual(result.status_code, 303, result.content)
        return self.author.get(AUTHOR_BASE + '?split=1')

    def decision_fields(self, action='READY_FOR_SIGNATURE', note=''):
        page = self.mufti.get(MUFTI_BASE + '?split=1')
        self.assertEqual(page.status_code, 200, page.content)
        fields = {key: self.hidden(page, key) for key in ('csrfmiddlewaretoken', 'request_sha256', 'confirmation', 'command_id')}
        fields.update(split='1', action=action, note=note, acknowledge='1')
        return fields

    def test_provider_missing_and_feature_off_fail_without_sql(self):
        with override_settings(FATWA_MUFTI_REVIEW_ENABLED=False), CaptureQueriesContext(connection) as queries:
            response = self.mufti.get(MUFTI_LOGIN)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(queries), 0)
        with override_settings(FATWA_MUFTI_IDENTITY_PROVIDER=None), CaptureQueriesContext(connection) as queries:
            response = self.mufti.get(MUFTI_LOGIN)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(queries), 0)

    def test_author_cookie_cannot_open_mufti_decisions(self):
        self.login_author()
        self.assertEqual(self.author.get(MUFTI_BASE).status_code, 403)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_author_submission_then_mufti_ready_creates_no_signature_or_queue(self):
        self.submit()
        self.login_mufti()
        response = self.mufti.post(MUFTI_BASE + 'record/', self.decision_fields())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(b'READY_FOR_SIGNATURE', response.content)
        self.assertEqual(ApprovalClaim.objects.count(), 0)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    def test_return_note_is_visible_to_author_without_editing_source(self):
        before = self.fixture.files()
        self.submit()
        self.login_mufti()
        note = 'أعد تحرير المثال مع المحافظة على القيود.'
        response = self.mufti.post(MUFTI_BASE + 'record/', self.decision_fields('RETURN_FOR_CHANGES', note))
        self.assertEqual(response.status_code, 200)
        page = self.author.get(AUTHOR_BASE + '?split=1')
        self.assertIn(note, page.content.decode())
        self.assertNotIn('id="signed-response"', page.content.decode())
        self.assertEqual(self.fixture.files(), before)

    def test_login_and_decision_require_csrf_and_confirmation(self):
        self.assertEqual(self.mufti.post(MUFTI_LOGIN, {'credential': 'M' * 64}).status_code, 403)
        self.submit()
        self.login_mufti()
        fields = self.decision_fields()
        fields.pop('csrfmiddlewaretoken')
        self.assertEqual(self.mufti.post(MUFTI_BASE + 'record/', fields).status_code, 403)
        fields = self.decision_fields()
        fields['confirmation'] = '0' * 64
        self.assertEqual(self.mufti.post(MUFTI_BASE + 'record/', fields).status_code, 403)
        from apps.mufti_review.models import ReviewDecision
        self.assertEqual(ReviewDecision.objects.count(), 0)

    def test_identity_revocation_after_login_blocks_action(self):
        self.submit()
        self.login_mufti()
        fields = self.decision_fields()
        self.directory.current = replace(self.directory.current, active=False)
        self.assertEqual(self.mufti.post(MUFTI_BASE + 'record/', fields).status_code, 403)
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_cookie_without_browser_secret_does_not_authenticate(self):
        self.login_mufti()
        other = NativeFormClient(enforce_csrf_checks=True)
        other.cookies['fatwa_training_mufti'] = self.mufti.cookies['fatwa_training_mufti']
        self.assertEqual(other.get(MUFTI_BASE).status_code, 403)

    def test_old_decision_form_after_source_change_is_rejected(self):
        self.submit()
        self.login_mufti()
        fields = self.decision_fields()
        self.fixture.correct_source()
        response = self.mufti.post(MUFTI_BASE + 'record/', fields)
        self.assertEqual(response.status_code, 409, response.content)

    def test_same_native_decision_post_is_idempotent(self):
        self.submit()
        self.login_mufti()
        fields = self.decision_fields()
        for _ in range(2):
            self.assertEqual(self.mufti.post(MUFTI_BASE + 'record/', fields).status_code, 200)
        from apps.mufti_review.models import ReviewDecision
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_decision_export_is_not_a_signed_approval(self):
        self.submit()
        self.login_mufti()
        self.mufti.post(MUFTI_BASE + 'record/', self.decision_fields())
        export = self.mufti.get(MUFTI_BASE + 'decision.json?split=1')
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.json()['status'], 'HUMAN_REVIEW_ONLY_NOT_SIGNED')
        self.assertNotIn('signature_b64url', export.content.decode())
        self.assertIn('no-store', export['Cache-Control'])
        self.assertEqual(self.mufti.head(MUFTI_BASE + 'decision.json?split=1').content, b'')

    def test_valid_receipt_cannot_bypass_pending_human_review(self):
        page = self.submit()
        package = self.author.get(AUTHOR_BASE + 'request.json?split=1').json()
        fields = {key: self.hidden(page, key) for key in ('csrfmiddlewaretoken', 'request_sha256', 'confirmation')}
        fields.update(split='1', acknowledge='1', response=self.fixture.signed_response(package))
        response = self.author.post(AUTHOR_BASE + 'receipt/', fields)
        self.assertIn(response.status_code, (403, 409))
        self.assertEqual(ApprovalClaim.objects.count(), 0)

    def test_non_loopback_mutating_get_and_duplicate_fields_are_rejected(self):
        self.assertEqual(self.mufti.get(MUFTI_LOGIN, REMOTE_ADDR='198.51.100.1').status_code, 403)
        self.assertEqual(self.mufti.get(MUFTI_BASE + 'record/').status_code, 405)
        self.submit()
        self.login_mufti()
        fields = self.decision_fields()
        fields['action'] = ['READY_FOR_SIGNATURE', 'DECLINED']
        self.assertEqual(self.mufti.post(MUFTI_BASE + 'record/', fields).status_code, 400)
