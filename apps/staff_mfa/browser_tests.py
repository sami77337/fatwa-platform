"""Protected native password/TOTP, revocation and recovery on actual role routes."""

import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import AnswerRevision, CaseDecision, CaseEvidence, CaseSource
from apps.casework_web.access import COOKIE as MUFTI_COOKIE
from apps.operational_workspace.access import COOKIE as ADMIN_COOKIE
from apps.staff_sessions.models import Session

from . import crypto, views
from .models import Factor, FactorRevocation, Proof, RecoveryUse, SessionAssurance
from .native_test_support import NATIVE, NativeFixture
from .test_support import PASSWORDS

OUT = Path(".local/qa/functional-continuation/staff-mfa-browser")


@override_settings(**{**NATIVE, "ROOT_URLCONF": "config.campaign_urls"})
class StaffMfaBrowserTests(NativeFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, call):
        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    @staticmethod
    def original_snapshot():
        return {
            model._meta.db_table: list(model.objects.order_by("pk").values())
            for model in (CaseSource, CaseEvidence, AnswerRevision, CaseDecision)
        }

    def submit(self, page, button, *, expected=200):
        # These forms deliberately share the existing small login budget. The
        # native proof waits for that budget instead of weakening the product.
        now = time.monotonic()
        self.posts = [stamp for stamp in self.posts if now - stamp < 61]
        if len(self.posts) >= 9:
            page.wait_for_timeout(max(0, self.posts[0] + 61 - now) * 1000)
        self.posts.append(time.monotonic())
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, expected, page.locator("body").inner_text()[:500])
        return response.value

    def capture(self, page, name, *, html=True):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            if html:
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def token(self, page, secret, *, used=None):
        period = self.authority.rule.period
        stamp = int(time.time())
        if used is not None and stamp // period == used:
            page.wait_for_timeout(((used + 1) * period - stamp + 1) * 1000)
            stamp = int(time.time())
        return crypto.generate(
            secret=secret,
            algorithm=self.authority.rule.algorithm,
            digits=self.authority.rule.digits,
            period=period,
            at=stamp,
        ), stamp // period

    def secret_from_page(self, page):
        manual = page.locator("#mfa-manual-key").inner_text()
        self.assertIn(
            self.authority.rule.algorithm, page.locator("#mfa-enrollment-secret").inner_text()
        )
        return base64.b32decode(manual + "=" * ((-len(manual)) % 8))

    def no_staff_cookie(self, context, surface):
        name = MUFTI_COOKIE if surface == "CASEWORK" else ADMIN_COOKIE
        self.assertFalse(any(row["name"] == name and row["value"] for row in context.cookies()))

    def test_native_two_roles_real_totp_factor_revocation_and_one_use_recovery(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected native MFA proof requires FATWA_BROWSER_SANDBOX=1")
        self.assertEqual(settings.ROOT_URLCONF, "config.campaign_urls")
        self.assertIn("apps.staff_sessions.middleware.SessionContext", settings.MIDDLEWARE)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        original = self.original_snapshot()
        question = original[CaseSource._meta.db_table][0]["original_question"]
        self.posts = []
        contexts, errors, external, people = [], [], [], {}
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            try:
                for subject, surface, denied_status in (
                    ("mufti", "CASEWORK", 403),
                    ("admin", "OPERATIONS", 409),
                ):
                    context = browser.new_context(viewport={"width": 320, "height": 900})
                    contexts.append(context)

                    def route(request):
                        url = urlsplit(request.request.url)
                        if (
                            url.scheme != "http"
                            or url.netloc != urlsplit(self.live_server_url).netloc
                        ):
                            external.append(request.request.url)
                            request.abort()
                        else:
                            request.continue_()

                    context.route("**/*", route)
                    context.tracing.start(screenshots=True, snapshots=True)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    home, path = views.HOMES[surface], views.PATHS[surface]
                    self.assertEqual(page.goto(self.live_server_url + home + "login/").status, 200)
                    page.locator('[name="credential"]').fill(PASSWORDS[subject])
                    self.submit(page, page.locator('form:has(input[name="credential"]) button'))
                    self.no_staff_cookie(context, surface)
                    self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    self.capture(page, subject + "-primary-only")
                    refused = page.goto(self.live_server_url + home)
                    self.assertEqual(refused.status, denied_status)
                    self.assertNotIn(question, page.locator("body").inner_text())
                    self.assertEqual(page.goto(self.live_server_url + path).status, 200)
                    self.submit(
                        page,
                        page.get_by_role("button", name="تسجيل عامل تحقق لهذا الحساب", exact=True),
                    )
                    secret = self.secret_from_page(page)
                    self.capture(page, subject + "-confirm-enrollment")
                    # A GET cannot reveal the setup seed again or create another factor.
                    self.assertEqual(page.goto(self.live_server_url + path).status, 200)
                    self.assertEqual(page.locator("#mfa-manual-key").count(), 0)
                    code, counter = self.token(page, secret)
                    if subject == "mufti":
                        accepted = {
                            crypto.generate(
                                secret=secret,
                                algorithm=self.authority.rule.algorithm,
                                digits=self.authority.rule.digits,
                                period=self.authority.rule.period,
                                at=(counter + offset) * self.authority.rule.period,
                            )
                            for offset in (-1, 0, 1)
                        }
                        wrong = next(
                            str(value).zfill(self.authority.rule.digits)
                            for value in range(4)
                            if str(value).zfill(self.authority.rule.digits) not in accepted
                        )
                        page.locator("#mfa-code").fill(wrong)
                        response = self.submit(
                            page,
                            page.get_by_role(
                                "button", name="تأكيد تسجيل العامل والدخول", exact=True
                            ),
                            expected=403,
                        )
                        self.assertEqual(response.json(), {"error": "staff_mfa_not_authorized"})
                        self.no_staff_cookie(context, surface)
                        self.capture(page, "wrong-totp-denied", html=False)
                        page.goto(self.live_server_url + path)
                        code, counter = self.token(page, secret)
                    page.locator("#mfa-code").fill(code)
                    self.submit(
                        page,
                        page.get_by_role("button", name="تأكيد تسجيل العامل والدخول", exact=True),
                    )
                    self.assertEqual(page.locator("#mfa-completed").count(), 1)
                    codes = page.locator("#mfa-recovery-codes code").all_text_contents()
                    self.assertEqual(len(codes), self.authority.rule.recovery_codes)
                    self.capture(page, subject + "-two-factors-complete")
                    self.assertEqual(page.goto(self.live_server_url + home).status, 200)
                    self.assertIn(self.receipt["public_ref"], page.locator("body").inner_text())
                    people[subject] = (page, context, secret, counter, codes)
                self.assertEqual(
                    self.sync(lambda: set(Session.objects.values_list("role", flat=True))),
                    {"MUFTI", "ORGANIZER_ADMIN"},
                )
                page, context, secret, counter, codes = people["mufti"]
                copied = browser.new_context()
                contexts.append(copied)
                copied.route("**/*", route)
                copied.tracing.start(screenshots=True, snapshots=True)
                copied.add_cookies(context.cookies())
                old = copied.new_page()
                old.on("pageerror", lambda error: errors.append(str(error)))
                self.assertEqual(
                    old.goto(self.live_server_url + views.HOMES["CASEWORK"]).status, 200
                )
                self.assertEqual(
                    page.goto(self.live_server_url + views.PATHS["CASEWORK"]).status, 200
                )
                page.locator("#mfa-primary").fill(PASSWORDS["mufti"])
                self.submit(
                    page, page.get_by_role("button", name="إعادة التحقق لإبطال العامل", exact=True)
                )
                code, _ = self.token(page, secret, used=counter)
                page.locator("#mfa-code").fill(code)
                self.submit(
                    page, page.get_by_role("button", name="تأكيد إبطال عامل التحقق", exact=True)
                )
                # The native 303 ends at the login form. A copied previously valid
                # cookie and CSRF secret cannot revive the now-revoked factor.
                self.assertTrue(page.url.endswith("/casework/staff/login/"))
                self.assertEqual(
                    old.goto(self.live_server_url + views.HOMES["CASEWORK"]).status, 403
                )
                self.assertNotIn(self.receipt["public_ref"], old.locator("body").inner_text())
                page.locator('[name="credential"]').fill(PASSWORDS["mufti"])
                self.submit(page, page.locator('form:has(input[name="credential"]) button'))
                self.assertEqual(
                    page.get_by_role(
                        "button", name="تسجيل عامل تحقق لهذا الحساب", exact=True
                    ).count(),
                    0,
                )
                page.locator("#mfa-recovery summary").focus()
                page.locator("#mfa-recovery summary").press("Enter")
                page.locator("#mfa-recovery-code").fill(codes[0])
                self.submit(
                    page, page.get_by_role("button", name="استرداد العامل برمز محفوظ", exact=True)
                )
                self.no_staff_cookie(context, "CASEWORK")
                self.submit(
                    page, page.get_by_role("button", name="تسجيل عامل تحقق لهذا الحساب", exact=True)
                )
                replacement = self.secret_from_page(page)
                self.assertNotEqual(replacement, secret)
                code, _ = self.token(page, replacement)
                page.locator("#mfa-code").fill(code)
                self.submit(
                    page, page.get_by_role("button", name="تأكيد تسجيل العامل والدخول", exact=True)
                )
                self.capture(page, "recovered-factor-confirmed")
                self.assertEqual(
                    page.goto(self.live_server_url + views.HOMES["CASEWORK"]).status, 200
                )
                self.assertIn(self.receipt["public_ref"], page.locator("body").inner_text())
                self.authority.denied.add("USE")
                self.assertEqual(
                    page.goto(self.live_server_url + views.HOMES["CASEWORK"]).status, 403
                )
                self.assertNotIn(self.receipt["public_ref"], page.locator("body").inner_text())
                self.authority.denied.clear()
                self.assertEqual(
                    page.goto(self.live_server_url + views.HOMES["CASEWORK"]).status, 200
                )
                self.assertEqual(self.sync(lambda: Factor.objects.count()), 3)
                self.assertEqual(self.sync(lambda: Proof.objects.count()), 4)
                self.assertEqual(self.sync(lambda: SessionAssurance.objects.count()), 3)
                self.assertEqual(self.sync(lambda: FactorRevocation.objects.count()), 1)
                self.assertEqual(self.sync(lambda: RecoveryUse.objects.count()), 1)
                self.assertEqual(self.sync(self.original_snapshot), original)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_roles": ["MUFTI", "ORGANIZER_ADMIN"],
                            "native_primary_only_denied": True,
                            "real_totp_confirmed": True,
                            "setup_secret_not_redisplayed": True,
                            "wrong_totp_denied": True,
                            "revoked_factor_denied_copied_session": True,
                            "no_bootstrap_after_revocation": True,
                            "native_recovery_replacement_confirmed": True,
                            "recovery_consumed": 1,
                            "sessions_with_two_factors": 3,
                            "current_policy_revocation_denied": True,
                            "positive_read_after_denial": True,
                            "original_bytes_preserved": True,
                            "keyboard_submit": True,
                            "external_requests": external,
                            "page_errors": errors,
                            "production_assurance": "NOT_EVALUATED",
                            "phishing_resistant": False,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"trace-{index}.zip"))
                    context.close()
                browser.close()
