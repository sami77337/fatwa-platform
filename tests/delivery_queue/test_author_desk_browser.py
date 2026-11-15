"""Native author login, external synthetic signing and staging in real Chrome."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
from unittest.mock import patch
from urllib.parse import urlsplit
from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings
from apps.delivery_queue.models import ApprovalClaim, DeliveryIntent, DeliveryAttempt
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from tests.delivery_queue.author_desk_fixtures import JournalFixture, BODY

BASE = '/review/author/approval/'
OUTPUT = Path('.local/qa/trusted-journey/author-browser')


@override_settings(ROOT_URLCONF='apps.delivery_queue.author_urls',
    ALLOWED_HOSTS=['127.0.0.1', 'localhost', 'testserver'],
    MIDDLEWARE=['apps.delivery_queue.author_http.AuthorDeskGuard', 'django.middleware.csrf.CsrfViewMiddleware'],
    CSRF_COOKIE_NAME='fatwa_training_desk_csrf', CSRF_COOKIE_PATH='/review/',
    CSRF_COOKIE_HTTPONLY=True, CSRF_COOKIE_SECURE=False, CSRF_COOKIE_SAMESITE='Strict')
class AuthorDeskBrowserTests(LiveServerTestCase):
    host = '127.0.0.1'

    def setUp(self):
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()
        self.token = secrets.token_hex(32)
        env = patch.dict(os.environ, {'FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256': sha256(self.token.encode()).hexdigest()})
        env.start()
        self.addCleanup(env.stop)
        config = override_settings(FATWA_AUTHOR_APPROVAL_ENABLED=True,
            FATWA_AUTHOR_APPROVAL_DIRECTORY=self.fixture.directory,
            FATWA_AUTHOR_APPROVAL_CASES=(CASE_KEY,), FATWA_AUTHOR_APPROVAL_MAX_CHARS=32,
            FATWA_AUTHOR_APPROVAL_VERIFIER=self.fixture.verifier)
        config.enable()
        self.addCleanup(config.disable)

    def database_snapshot(self):
        def query():
            close_old_connections()
            try:
                return {'claims': ApprovalClaim.objects.count(), 'attempts': DeliveryAttempt.objects.count(),
                    'states': list(DeliveryIntent.objects.order_by('ordinal').values_list('state', flat=True))}
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(query).result(timeout=10)

    def test_native_author_request_and_signed_receipt_stage_without_send(self):
        self.assertIsNotNone(importlib.util.find_spec('apps.delivery_queue.author_http'))
        from playwright.sync_api import sync_playwright
        chrome = os.environ.get('FATWA_FASTBUILD_BROWSER') or shutil.which('google-chrome')
        self.assertTrue(chrome and Path(chrome).is_file())
        OUTPUT.mkdir(parents=True, exist_ok=True)
        evidence = {'status': 'ERROR', 'views': [], 'page_errors': [], 'external_requests': [],
                    'journal_unchanged': False, 'native_login_statuses': []}
        before = self.fixture.files()
        origin = self.live_server_url
        netloc = urlsplit(origin).netloc
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chrome, headless=True, chromium_sandbox=True)
            evidence['browser_version'] = browser.version
            try:
                context = browser.new_context()
                def route(route):
                    parsed = urlsplit(route.request.url)
                    if parsed.scheme == 'http' and parsed.netloc == netloc:
                        route.continue_()
                    else:
                        evidence['external_requests'].append(route.request.url)
                        route.abort()
                context.route('**/*', route)
                page = context.new_page()
                page.on('pageerror', lambda error: evidence['page_errors'].append(str(error)))
                page.on('response', lambda response: evidence['native_login_statuses'].append(response.status)
                    if response.request.method == 'POST' and response.url.endswith('/login/') else None)
                self.assertEqual(page.goto(origin + BASE).status, 403)
                self.assertEqual(context.request.post(origin + BASE + 'login/', form={'token': self.token}).status, 403)
                page.goto(origin + BASE + 'login/')
                page.locator('#author-token').fill(self.token)
                with page.expect_navigation():
                    page.get_by_role('button', name='دخول المؤلف').click()
                self.assertIn(303, evidence['native_login_statuses'])
                for width, height in ((320, 780), (1280, 900)):
                    page.set_viewport_size({'width': width, 'height': height})
                    self.assertEqual(page.goto(origin + BASE + '?split=1').status, 200)
                    self.assertEqual(page.locator('html').get_attribute('dir'), 'rtl')
                    self.assertIn('طلب اعتماد', page.locator('body').inner_text())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    page.keyboard.press('Tab')
                    self.assertEqual(page.evaluate('document.activeElement.getAttribute("href")'), '#main')
                    page.keyboard.press('Enter')
                    self.assertEqual(page.evaluate('document.activeElement.id'), 'main')
                    page.screenshot(path=str(OUTPUT / f'author-{width}.png'), full_page=True)
                    evidence['views'].append({'width': width, 'height': height, 'rtl': True,
                        'no_overflow': True, 'keyboard_skip': True})
                request_response = context.request.get(origin + BASE + 'request.json?split=1')
                self.assertEqual(request_response.status, 200)
                self.assertIn('no-store', request_response.headers['cache-control'])
                request = request_response.json()
                self.assertEqual(request['answer']['body'], BODY)
                self.assertEqual(''.join(s['exact_text'] for s in request['segments']), BODY)
                self.assertEqual(self.database_snapshot()['claims'], 0)
                # This signer belongs to the test only; production UI never
                # generates a MUFTI signature or receives a private key.
                signed = self.fixture.signed_response(request)
                page.locator('#signed-response').fill(signed)
                page.locator('#acknowledge').check()
                with page.expect_navigation():
                    page.get_by_role('button', name='تسجيل الإيصال وتجهيز الطابور').click()
                self.assertIn('STAGED_NOT_SENT', page.locator('body').inner_text())
                snapshot = self.database_snapshot()
                self.assertEqual(snapshot, {'claims': 1, 'attempts': 0,
                    'states': ['STAGED'] * len(request['segments'])})
                page.screenshot(path=str(OUTPUT / 'staged.png'), full_page=True)
                self.assertEqual(self.fixture.files(), before)
                self.assertEqual(evidence['page_errors'], [])
                self.assertEqual(evidence['external_requests'], [])
                evidence.update(status='PASS', journal_unchanged=True,
                    request_preserved_exact_text=True, staged_parts=len(request['segments']), attempts=0)
                context.close()
            finally:
                browser.close()
                (OUTPUT / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
