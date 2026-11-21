"""One protected native organizer review and independently granted publication decision."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from . import browser_tests
from .publication_test_support import PUBLICATION_FEATURES, PublicationFixture
from .test_support import CREDENTIALS

OUT = Path(".local/qa/functional-continuation/operational-publication-browser")


@override_settings(**PUBLICATION_FEATURES)
class OperationalPublicationBrowserTests(PublicationFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_tests.OperationalWorkspaceBrowserTests.sync
    submit = browser_tests.OperationalWorkspaceBrowserTests.submit

    def open_manager(self, page):
        page.locator("#ops-publication-index > summary").click()
        entry = page.locator(
            f'#ops-publication-index form[data-case-ref="{self.target["public_ref"]}"]'
        )
        self.assertEqual(entry.count(), 1)
        self.submit(page, entry.locator("button"))

    def login_native(self, page, subject):
        base = self.live_server_url + "/casework/operations/"
        self.assertEqual(page.goto(base + "login/").status, 200)
        page.locator('[name="credential"]').fill(CREDENTIALS[subject])
        self.submit(page, page.locator("#ops-login button"))
        self.open_manager(page)

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_organizer_publication_review_admin_approval_and_withdrawal_preserve_source(
        self,
    ):
        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.skipTest("protected browser sandbox required")
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external = [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER") or None,
                headless=True,
                chromium_sandbox=True,
            )
            contexts = {
                subject: browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
                for subject in ("operator", "admin")
            }
            pages = {}
            for subject, context in contexts.items():
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = pages[subject] = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: (
                        external.append(request.url)
                        if urlsplit(request.url).hostname not in {"127.0.0.1", "localhost"}
                        else None
                    ),
                )
            try:
                operator, admin = pages["operator"], pages["admin"]
                self.login_native(operator, "operator")
                self.assertIn("ORGANIZER", operator.locator("#ops-actor").inner_text())
                self.assertEqual(operator.locator('[name="body"]').count(), 0)
                self.assertEqual(operator.locator("#ops-publication-editions > article").count(), 1)
                self.assertEqual(
                    operator.locator(".ops-publication-body").inner_text(), self.edition.body
                )
                decision = operator.locator(".ops-publication-decision")
                self.assertEqual(decision.count(), 1)
                decision.locator('[name="confirmed"]').check()
                self.assertTrue(decision.evaluate("form => form.checkValidity()"))
                self.submit(operator, decision.locator('button[value="REVIEW"]'))
                self.assertEqual(operator.locator('[data-decision="REVIEW"]').count(), 1)
                self.assertEqual(operator.locator('button[value="APPROVE"]').count(), 0)
                self.screenshots(operator, "organizer-reviewed-mufti-copy")

                self.login_native(admin, "admin")
                self.assertIn("ORGANIZER_ADMIN", admin.locator("#ops-actor").inner_text())
                decision = admin.locator(".ops-publication-decision")
                decision.locator('[name="confirmed"]').check()
                saved_rules = set(self.authority.publication_rules)
                self.sync(
                    lambda: self.authority.revoke(
                        subject="admin", action="APPROVE_PUBLICATION_EDITION"
                    )
                )
                self.submit(admin, decision.locator('button[value="APPROVE"]'), expected=409)
                self.sync(lambda: setattr(self.authority, "publication_rules", saved_rules))
                self.assertEqual(
                    admin.goto(self.live_server_url + "/casework/operations/").status, 200
                )
                self.open_manager(admin)
                decision = admin.locator(".ops-publication-decision")
                decision.locator('[name="confirmed"]').check()
                self.submit(admin, decision.locator('button[value="APPROVE"]'))
                self.assertIn("اعتمدت للنشر", admin.locator(".ops-publication-state").inner_text())
                self.assertEqual(admin.locator('[data-decision="APPROVE"]').count(), 1)
                self.screenshots(admin, "independent-admin-publication-approval")

                self.submit(operator, operator.locator("#ops-publication-back button"))
                self.open_manager(operator)
                decision = operator.locator(".ops-publication-decision")
                decision.locator('[name="confirmed"]').check()
                self.submit(operator, decision.locator('button[value="WITHDRAW"]'))
                self.assertIn("مسحوبة", operator.locator(".ops-publication-state").inner_text())
                self.assertEqual(operator.locator('[data-decision="REVIEW"]').count(), 1)
                self.assertEqual(operator.locator('[data-decision="APPROVE"]').count(), 1)
                self.assertEqual(operator.locator('[data-decision="WITHDRAW"]').count(), 1)
                self.assertEqual(
                    self.sync(self.immutable_publication_sources), self.publication_originals
                )
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                for subject, context in contexts.items():
                    context.tracing.stop(path=str(OUT / f"{subject}-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_roles": ["ORGANIZER", "ORGANIZER_ADMIN"],
                            "checks": [
                                "native organizer reads exact Mufti-prepared edition with no free body editor",
                                "native explicit editorial/privacy review preserves actual reviewer",
                                "reviewer cannot approve own reviewed edition",
                                "revoked independent approval grant rejects already rendered form",
                                "native independently granted administrator approves exact current edition",
                                "native withdrawal keeps full review and approval history",
                                "original case answer scientific approval recording and edition body unchanged",
                            ],
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for subject, context in contexts.items():
                    if not (OUT / f"{subject}-trace.zip").exists():
                        context.tracing.stop(path=str(OUT / f"{subject}-trace.zip"))
                    context.close()
                browser.close()
