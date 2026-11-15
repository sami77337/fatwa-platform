"""Real Chrome: author -> return for changes -> new revision -> Mufti -> staged."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
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
from apps.mufti_review.models import ReviewRequest, ReviewDecision
from apps.fast9_case_source_join.answer_drafts import CASE_KEY
from tests.delivery_queue.author_desk_fixtures import JournalFixture, BODY
from tests.mufti_review.provider_fixture import FixtureDirectory

A = '/review/author/approval/'
M = '/review/mufti/decisions/'
OUT = Path('.local/qa/trusted-journey/mufti-browser')


@override_settings(ROOT_URLCONF='apps.mufti_review.urls',
    ALLOWED_HOSTS=['127.0.0.1', 'localhost', 'testserver'],
    MIDDLEWARE=['apps.mufti_review.views.ReviewDeskGuard', 'django.middleware.csrf.CsrfViewMiddleware'],
    CSRF_COOKIE_NAME='fatwa_training_desk_csrf', CSRF_COOKIE_PATH='/review/',
    CSRF_COOKIE_HTTPONLY=True, CSRF_COOKIE_SECURE=False, CSRF_COOKIE_SAMESITE='Strict')
class MuftiReviewBrowserTests(LiveServerTestCase):
    host = '127.0.0.1'

    def setUp(self):
        self.fixture = JournalFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.ready()
        self.author_token, self.mufti_token = secrets.token_hex(32), secrets.token_hex(32)
        self.provider = FixtureDirectory(self.mufti_token)
        env = patch.dict(os.environ, {'FATWA_SYNTHETIC_AUTHOR_TOKEN_SHA256': sha256(self.author_token.encode()).hexdigest()})
        env.start()
        self.addCleanup(env.stop)
        config = override_settings(FATWA_MUFTI_REVIEW_ENABLED=True, FATWA_AUTHOR_APPROVAL_ENABLED=True,
            FATWA_MUFTI_IDENTITY_PROVIDER=self.provider, FATWA_AUTHOR_APPROVAL_DIRECTORY=self.fixture.directory,
            FATWA_AUTHOR_APPROVAL_CASES=(CASE_KEY,), FATWA_AUTHOR_APPROVAL_MAX_CHARS=32,
            FATWA_AUTHOR_APPROVAL_VERIFIER=self.fixture.verifier)
        config.enable()
        self.addCleanup(config.disable)

    def sync(self, function):
        def call():
            close_old_connections()
            try:
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=15)

    def snapshot(self):
        return self.sync(lambda: {'reviews': ReviewRequest.objects.count(),
            'decisions': ReviewDecision.objects.count(), 'claims': ApprovalClaim.objects.count(),
            'attempts': DeliveryAttempt.objects.count(),
            'states': list(DeliveryIntent.objects.order_by('ordinal').values_list('state', flat=True))})

    def test_real_two_actor_revision_and_signed_staging_cycle(self):
        from playwright.sync_api import sync_playwright
        chrome = os.environ.get('FATWA_FASTBUILD_BROWSER') or shutil.which('google-chrome')
        self.assertTrue(chrome and Path(chrome).is_file())
        OUT.mkdir(parents=True, exist_ok=True)
        evidence = {'status': 'ERROR', 'views': [], 'page_errors': [], 'external_requests': [],
            'native_author_login': [], 'native_mufti_login': [], 'sent': False}
        origin = self.live_server_url
        netloc = urlsplit(origin).netloc
        initial_journal = self.fixture.files()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chrome, headless=True,
                chromium_sandbox=True, args=['--disable-dev-shm-usage'])
            evidence['browser_version'] = browser.version
            try:
                def context():
                    ctx = browser.new_context()
                    def route(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme == 'http' and parsed.netloc == netloc:
                            route.continue_()
                        else:
                            evidence['external_requests'].append(route.request.url)
                            route.abort()
                    ctx.route('**/*', route)
                    return ctx
                author_ctx, mufti_ctx = context(), context()
                author, mufti = author_ctx.new_page(), mufti_ctx.new_page()
                for page in (author, mufti):
                    page.on('pageerror', lambda error: evidence['page_errors'].append(str(error)))
                author.on('response', lambda response: evidence['native_author_login'].append(response.status)
                    if response.request.method == 'POST' and response.url.endswith(A + 'login/') else None)
                mufti.on('response', lambda response: evidence['native_mufti_login'].append(response.status)
                    if response.request.method == 'POST' and response.url.endswith('/review/mufti/login/') else None)
                self.assertEqual(mufti.goto(origin + M).status, 403)
                author.goto(origin + A + 'login/')
                author.locator('#author-token').fill(self.author_token)
                with author.expect_navigation():
                    author.get_by_role('button', name='دخول المؤلف').click()
                self.assertIn(303, evidence['native_author_login'])
                self.assertEqual(author_ctx.request.get(origin + M).status, 403)
                author.goto(origin + A + '?split=1')
                author.locator('#submit-acknowledge').check()
                with author.expect_navigation():
                    author.get_by_role('button', name='إرسال النسخة إلى المراجعة').click()
                self.assertIn('PENDING_REVIEW', author.locator('#review-state').inner_text())
                mufti.goto(origin + '/review/mufti/login/')
                mufti.locator('#mufti-credential').fill(self.mufti_token)
                with mufti.expect_navigation():
                    mufti.get_by_role('button', name='دخول المفتي').click()
                self.assertIn(303, evidence['native_mufti_login'])
                for width, height in ((320, 780), (1280, 900)):
                    mufti.set_viewport_size({'width': width, 'height': height})
                    response = mufti.goto(origin + M + '?split=1')
                    self.assertEqual(response.status, 200)
                    self.assertIn('no-store', response.headers['cache-control'])
                    self.assertEqual(mufti.locator('html').get_attribute('dir'), 'rtl')
                    self.assertLessEqual(mufti.evaluate('document.documentElement.scrollWidth'), width)
                    mufti.keyboard.press('Tab')
                    self.assertEqual(mufti.evaluate('document.activeElement.getAttribute("href")'), '#main')
                    mufti.keyboard.press('Enter')
                    self.assertEqual(mufti.evaluate('document.activeElement.id'), 'main')
                    mufti.screenshot(path=str(OUT / f'mufti-{width}.png'), full_page=True)
                    evidence['views'].append({'width': width, 'height': height,
                        'rtl': True, 'no_overflow': True, 'keyboard_skip': True})
                note = 'توضيح المثال مطلوب قبل الجاهزية للتوقيع.'
                mufti.locator('#decision-action').select_option('RETURN_FOR_CHANGES')
                mufti.locator('#decision-note').fill(note)
                mufti.locator('#decision-acknowledge').check()
                old_fields = mufti.locator('form[action="record/"]').evaluate('(form) => Object.fromEntries(new FormData(form))')
                with mufti.expect_navigation():
                    mufti.get_by_role('button', name='تسجيل قرار المراجعة').click()
                self.assertIn('RETURN_FOR_CHANGES', mufti.locator('body').inner_text())
                author.goto(origin + A + '?split=1')
                self.assertEqual(author.locator('#review-note').inner_text(), note)
                self.assertEqual(author.locator('#signed-response').count(), 0)
                author.screenshot(path=str(OUT / 'author-returned.png'), full_page=True)
                self.assertEqual(self.fixture.files(), initial_journal)
                self.assertEqual(self.snapshot()['claims'], 0)
                evidence['decision_did_not_change_journal'] = True

                # Only the existing editor's explicit human-revision API changes
                # the journal; the new review service never edits source text.
                revised_body = BODY + '\r\nنسخة بشرية ثانية للاختبار.'
                def revise():
                    self.fixture.draft(body=revised_body)
                    self.fixture.note('submit')
                    self.fixture.note('confirm')
                self.sync(revise)
                revised_journal = self.fixture.files()
                author.goto(origin + A + '?split=1')
                author.locator('#submit-acknowledge').check()
                with author.expect_navigation():
                    author.get_by_role('button', name='إرسال النسخة إلى المراجعة').click()
                stale = mufti_ctx.request.post(origin + M + 'record/', form=old_fields)
                self.assertEqual(stale.status, 409)
                mufti.goto(origin + M + '?split=1')
                mufti.locator('#decision-action').select_option('READY_FOR_SIGNATURE')
                mufti.locator('#decision-acknowledge').check()
                with mufti.expect_navigation():
                    mufti.get_by_role('button', name='تسجيل قرار المراجعة').click()
                self.assertIn('READY_FOR_SIGNATURE', mufti.locator('body').inner_text())
                self.assertEqual(self.snapshot()['claims'], 0)
                unsigned = mufti_ctx.request.get(origin + M + 'decision.json?split=1')
                self.assertEqual(unsigned.json()['status'], 'HUMAN_REVIEW_ONLY_NOT_SIGNED')
                self.assertNotIn('signature_b64url', unsigned.text())
                author.goto(origin + A + '?split=1')
                package = author_ctx.request.get(origin + A + 'request.json?split=1').json()
                self.assertEqual(package['answer']['body'], revised_body)
                signed = self.fixture.signed_response(package)
                author.locator('#signed-response').fill(signed)
                author.locator('#stage-acknowledge').check()
                with author.expect_navigation():
                    author.get_by_role('button', name='التحقق والتجهيز دون إرسال').click()
                self.assertIn('STAGED_NOT_SENT', author.locator('body').inner_text())
                result = self.snapshot()
                self.assertEqual(result, {'reviews': 2, 'decisions': 2, 'claims': 1, 'attempts': 0,
                    'states': ['STAGED'] * len(package['segments'])})
                self.assertEqual(self.fixture.files(), revised_journal)
                author.screenshot(path=str(OUT / 'reviewed-staged.png'), full_page=True)
                self.assertEqual(evidence['page_errors'], [])
                self.assertEqual(evidence['external_requests'], [])
                evidence.update(status='PASS', two_distinct_browsers=True,
                    stale_decision_rejected=True, original_decision_preserved=True,
                    current_text_preserved=True, result=result)
                author_ctx.close()
                mufti_ctx.close()
            finally:
                browser.close()
                (OUT / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
