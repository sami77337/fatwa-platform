"""Protected native two-role session journey; actual campaign routes and middleware."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from . import recovery_support
from .models import FreshProof, ProofUse, Session, SessionRevocation
from .test_support import CREDENTIALS, FEATURES, SessionFixture, operational_authority

OUT = Path(".local/qa/functional-continuation/staff-sessions-browser")
BROWSER = {
    key: value for key, value in FEATURES.items() if key not in {"ROOT_URLCONF", "MIDDLEWARE"}
}
BROWSER["ROOT_URLCONF"] = "config.campaign_urls"


@override_settings(**BROWSER)
class StaffSessionsBrowserTests(SessionFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, call):
        def run():
            close_old_connections()
            try:
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def submit(self, page, button):
        self.pace(page)
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, 200, page.locator("body").inner_text()[:600])

    def pace(self, page):
        # Keep the genuine 10/minute credential budget, including fixture logins
        # and denied forms. Observe it read-only and wait for the next window.
        from hashlib import sha256

        from apps.casework_web.models import ThrottleBucket

        window = int(time.time()) // 60
        key = sha256(b"127.0.0.1|login").hexdigest()
        used = self.sync(
            lambda: (
                ThrottleBucket.objects.filter(key=key, window=window)
                .values_list("requests", flat=True)
                .first()
            )
        )
        if used is not None and used >= 9:
            page.wait_for_timeout(max(0, int(((window + 1) * 60 - time.time() + 0.2) * 1000)))

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_mufti_and_admin_fresh_confirmation_revoke_only_exact_session(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("protected browser requires FATWA_BROWSER_SANDBOX=1")
        self.assertIn("apps.staff_sessions.middleware.SessionContext", settings.MIDDLEWARE)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        before = self.sync(lambda: recovery_support.sources(self.receipt["case_id"]))
        errors, external = [], []
        with (
            override_settings(
                FATWA_OPERATIONAL_WORKSPACE_ENABLED=True,
                FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=operational_authority(self.receipt),
            ),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            contexts = []
            try:
                pages = []
                for subject in ("mufti", "admin"):
                    context = browser.new_context(viewport={"width": 320, "height": 900})
                    contexts.append(context)

                    def route(request):
                        address = urlsplit(request.request.url)
                        if (
                            address.scheme != "http"
                            or address.netloc != urlsplit(self.live_server_url).netloc
                        ):
                            external.append(request.request.url)
                            request.abort()
                        else:
                            request.continue_()

                    context.route("**/*", route)
                    context.tracing.start(screenshots=True, snapshots=True)
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    prefix = "/casework/staff/" if subject == "mufti" else "/casework/operations/"
                    page.goto(self.live_server_url + prefix + "login/")
                    page.locator('[name="credential"]').fill(CREDENTIALS[subject])
                    self.submit(
                        page, page.locator('form:has(input[name="credential"]) button').first
                    )
                    address = (
                        "/casework/sessions/"
                        if subject == "mufti"
                        else "/casework/operations/sessions/"
                    )
                    self.assertEqual(
                        page.get_by_role("link", name="جلسات الحساب", exact=True).get_attribute(
                            "href"
                        ),
                        address,
                    )
                    with page.expect_navigation(wait_until="domcontentloaded") as response:
                        page.get_by_role("link", name="جلسات الحساب", exact=True).click()
                    self.assertEqual(response.value.status, 200)
                    pages.append(page)
                mufti, admin = pages
                target = self.session_id(self.other_client)
                target_form = mufti.locator(
                    f'form:has([name="action"][value="select"]):has([name="target_id"][value="{target}"])'
                )
                self.submit(mufti, target_form.locator("button"))
                self.assertEqual(self.sync(lambda: SessionRevocation.objects.count()), 0)
                mufti.locator('[name="credential"]').fill(CREDENTIALS["mufti"])
                self.submit(
                    mufti, mufti.get_by_role("button", name="إعادة التحقق لهذه العملية", exact=True)
                )
                self.assertEqual(self.sync(lambda: SessionRevocation.objects.count()), 0)
                self.capture(mufti, "fresh-proof-before-confirmation")
                self.submit(
                    mufti, mufti.get_by_role("button", name="إبطال الجلسة المحددة", exact=True)
                )
                self.assertEqual(
                    self.sync(lambda: self.other_client.get("/casework/staff/").status_code), 403
                )
                self.assertEqual(
                    self.sync(lambda: (FreshProof.objects.count(), ProofUse.objects.count())),
                    (1, 1),
                )
                own_target = self.session_id(self.client)
                form = admin.locator('form:has(input[name="target_id"]:not([type="hidden"]))')
                form.locator('[name="target_id"]').fill(own_target)
                self.pace(admin)
                with admin.expect_navigation(wait_until="domcontentloaded") as refused:
                    form.locator("button").press("Enter")
                self.assertEqual(refused.value.status, 403)
                self.authority.admin_targets.add(own_target)
                admin.goto(self.live_server_url + "/casework/operations/sessions/")
                form = admin.locator('form:has(input[name="target_id"]:not([type="hidden"]))')
                form.locator('[name="target_id"]').fill(own_target)
                self.submit(admin, form.locator("button"))
                admin.locator('[name="credential"]').fill(CREDENTIALS["admin"])
                self.submit(
                    admin, admin.get_by_role("button", name="إعادة التحقق لهذه العملية", exact=True)
                )
                self.capture(admin, "explicit-admin-permission")
                self.submit(
                    admin, admin.get_by_role("button", name="إبطال الجلسة المحددة", exact=True)
                )
                self.assertEqual(
                    self.sync(lambda: self.client.get("/casework/staff/").status_code), 403
                )
                self.assertEqual(
                    admin.goto(self.live_server_url + "/casework/operations/").status, 200
                )
                self.assertEqual(
                    self.sync(lambda: recovery_support.sources(self.receipt["case_id"])), before
                )
                self.assertEqual(
                    self.sync(lambda: Session.objects.filter(role="ORGANIZER_ADMIN").count()), 1
                )
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_roles": ["MUFTI", "ORGANIZER_ADMIN"],
                            "proofs": 2,
                            "consumed_proofs": 2,
                            "revoked_sessions": 2,
                            "separate_human_confirmation": True,
                            "admin_default_denied": True,
                            "canonical_sources_unchanged": True,
                            "external_requests": external,
                            "page_errors": errors,
                            "mfa_assurance": "NOT_EVALUATED",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for i, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"trace-{i}.zip"))
                    context.close()
                browser.close()
