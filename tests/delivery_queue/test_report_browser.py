"""Actual sandboxed Chrome over a loopback server and owned PostgreSQL."""
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings
from django.utils import timezone
from apps.delivery_queue import services as q
from apps.delivery_queue.models import (
    ApprovalClaim, DeliveryAttempt, DeliveryAuditEvent, DeliveryAuditHead,
    DeliveryIntent, ProviderReceipt, SignedDeliveryContext,
)

OUTPUT = Path('.local/qa/trusted-journey/browser')


@override_settings(
    ROOT_URLCONF='apps.delivery_queue.review_urls',
    ALLOWED_HOSTS=['127.0.0.1', 'localhost', 'testserver'],
    FATWA_PG_DELIVERY_REPORTS_ENABLED=True,
    FATWA_PG_DELIVERY_OPERATOR_CASES={'synthetic-operator': ('browser-allowed',)},
    CSRF_COOKIE_NAME='fatwa_training_desk_csrf',
    CSRF_COOKIE_PATH='/review/', CSRF_COOKIE_SECURE=False,
    CSRF_COOKIE_HTTPONLY=True, CSRF_COOKIE_SAMESITE='Strict',
    SECURE_REFERRER_POLICY='same-origin',
    MIDDLEWARE=[
        'django.middleware.security.SecurityMiddleware',
        'apps.delivery_queue.review_http.LoopbackReviewGuard',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
    ],
)
class DeliveryReportBrowserTests(LiveServerTestCase):
    host = '127.0.0.1'

    def setUp(self):
        self.token = secrets.token_hex(32)
        self.patch_env = patch.dict(os.environ, {
            'FATWA_SYNTHETIC_OPERATOR_TOKEN_SHA256': sha256(self.token.encode()).hexdigest(),
        })
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        for case, fingerprint, nonce in (
            ('browser-allowed', 'c' * 64, 'A' * 40),
            ('browser-hidden', 'd' * 64, 'B' * 40),
        ):
            q.commit_approved_plan(receipt_id='approval-' + case, nonce=nonce,
                approval_fingerprint='a' * 64, plan_fingerprint=fingerprint,
                case_key=case, answer_revision=2, provider='reply-source',
                expires_at=timezone.now() + timedelta(minutes=5),
                parts=((1, 'a' * 64), (2, 'b' * 64)), verify_approval=lambda: True)
        lease = q.claim_next(provider='reply-source', worker_id='browser-worker', plan_fingerprint='c' * 64)
        q.record_receipt(lease=lease, receipt_reference='browser-proof',
            provider_message_id='browser-message', reported='DELIVERED',
            verify_provider_receipt=lambda proof: True)

    def snapshot(self):
        return {
            model._meta.label: list(model.objects.order_by('pk').values())
            for model in (ApprovalClaim, DeliveryIntent, DeliveryAttempt,
                          ProviderReceipt, DeliveryAuditEvent, DeliveryAuditHead, SignedDeliveryContext)
        }

    def test_native_login_mobile_desktop_scope_keyboard_and_read_only_export(self):
        from playwright.sync_api import sync_playwright
        chrome = os.environ.get('FATWA_FASTBUILD_BROWSER') or shutil.which('google-chrome')
        self.assertTrue(chrome and Path(chrome).is_file(), 'real_chrome_is_required_not_skipped')
        OUTPUT.mkdir(parents=True, exist_ok=True)
        evidence = {'status': 'ERROR', 'views': [], 'page_errors': [],
                    'external_requests': [], 'native_login_statuses': [],
                    'journal_unchanged': False}
        before = self.snapshot()
        origin = self.live_server_url
        allowed = urlsplit(origin)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chrome, headless=True,
                chromium_sandbox=True, args=['--disable-dev-shm-usage'])
            evidence['browser_version'] = browser.version
            try:
                context = browser.new_context()
                def route_request(route):
                    parsed = urlsplit(route.request.url)
                    if parsed.scheme in ('http', 'https') and (parsed.scheme, parsed.netloc) == (allowed.scheme, allowed.netloc):
                        route.continue_()
                    else:
                        evidence['external_requests'].append(route.request.url)
                        route.abort()
                context.route('**/*', route_request)
                page = context.new_page()
                page.on('pageerror', lambda error: evidence['page_errors'].append(str(error)))
                page.on('response', lambda response: evidence['native_login_statuses'].append(response.status)
                        if response.request.method == 'POST' and response.url.endswith('/review/operator/login/') else None)
                unauthorized = page.goto(origin + '/review/operator/postgres/')
                self.assertEqual(unauthorized.status, 403)
                forged = context.request.post(origin + '/review/operator/login/', form={'token': self.token})
                self.assertEqual(forged.status, 403)
                page.goto(origin + '/review/operator/login/')
                page.locator('#operator-token').fill(self.token)
                with page.expect_navigation():
                    page.get_by_role('button', name='فتح المتابعة').click()
                self.assertTrue(page.url.endswith('/review/operator/postgres/'))
                self.assertIn(303, evidence['native_login_statuses'])
                role_cookie = next(cookie for cookie in context.cookies() if cookie['name'] == 'fatwa_training_operator')
                self.assertTrue(role_cookie['httpOnly'])
                self.assertEqual(role_cookie['sameSite'], 'Strict')
                for width, height in ((320, 780), (1280, 900)):
                    page.set_viewport_size({'width': width, 'height': height})
                    response = page.goto(origin + '/review/operator/postgres/')
                    self.assertEqual(response.status, 200)
                    self.assertIn('no-store', response.headers['cache-control'])
                    self.assertEqual(page.locator('html').get_attribute('dir'), 'rtl')
                    body = page.locator('body').inner_text()
                    self.assertIn('browser-allowed', body)
                    self.assertNotIn('browser-hidden', body)
                    self.assertIn('PARTIALLY_DELIVERED', body)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    page.keyboard.press('Tab')
                    self.assertEqual(page.evaluate('document.activeElement.getAttribute("href")'), '#main')
                    page.keyboard.press('Enter')
                    self.assertEqual(page.evaluate('document.activeElement.id'), 'main')
                    page.screenshot(path=str(OUTPUT / f'report-{width}.png'), full_page=True)
                    evidence['views'].append({'width': width, 'height': height,
                        'rtl': True, 'no_overflow': True, 'keyboard_skip': True, 'scope_isolated': True})
                report = context.request.get(origin + '/review/operator/postgres.json')
                self.assertEqual(report.status, 200)
                payload = report.json()
                self.assertEqual(len(payload['plans']), 1)
                self.assertEqual(payload['plans'][0]['delivered_parts'], 1)
                serialized = json.dumps(payload)
                for forbidden in (self.token, 'browser-hidden', 'lease_owner', 'signature', 'nonce', 'envelope'):
                    self.assertNotIn(forbidden, serialized)
                head = context.request.head(origin + '/review/operator/postgres.json')
                self.assertEqual(head.status, 200)
                self.assertEqual(head.body(), b'')
                mutation = context.request.post(origin + '/review/operator/postgres.json', data='{}')
                self.assertEqual(mutation.status, 405)
                stolen_context = browser.new_context()
                stolen_context.add_cookies([role_cookie])
                self.assertEqual(stolen_context.request.get(origin + '/review/operator/postgres.json').status, 403)
                stolen_context.close()
                context.close()
                self.assertEqual(self.snapshot(), before)
                evidence['journal_unchanged'] = True
                self.assertEqual(evidence['page_errors'], [])
                self.assertEqual(evidence['external_requests'], [])
                evidence['status'] = 'PASS'
            finally:
                browser.close()
                (OUTPUT / 'browser-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
