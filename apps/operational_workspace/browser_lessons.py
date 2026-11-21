"""One protected native organizer proposal, independent admin review and withdrawal."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from . import browser_tests
from .lesson_test_support import LESSON_FEATURES, LessonFixture
from .test_support import CREDENTIALS

OUT = Path(".local/qa/functional-continuation/operational-lessons-browser")


@override_settings(**LESSON_FEATURES)
class OperationalLessonsBrowserTests(LessonFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_tests.OperationalWorkspaceBrowserTests.sync
    submit = browser_tests.OperationalWorkspaceBrowserTests.submit

    def open_native(self, page, subject):
        base = self.live_server_url + "/casework/operations/"
        self.assertEqual(page.goto(base + "login/").status, 200)
        page.locator('[name="credential"]').fill(CREDENTIALS[subject])
        self.submit(page, page.locator("#ops-login button"))
        page.locator("#ops-lessons-index > summary").click()
        entry = page.locator(
            f'#ops-lessons-index form[data-case-ref="{self.target["public_ref"]}"]'
        )
        self.assertEqual(entry.count(), 1)
        self.submit(page, entry.locator("button"))

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_organizer_lesson_proposal_admin_review_and_withdrawal_preserve_sources(self):
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
            operator = browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
            admin = browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
            operator.tracing.start(screenshots=True, snapshots=True, sources=True)
            admin.tracing.start(screenshots=True, snapshots=True, sources=True)
            page, reviewer = operator.new_page(), admin.new_page()
            for surface in (page, reviewer):
                surface.on("pageerror", lambda error: errors.append(str(error)))
                surface.on(
                    "request",
                    lambda request: (
                        external.append(request.url)
                        if urlsplit(request.url).hostname not in {"127.0.0.1", "localhost"}
                        else None
                    ),
                )
            try:
                self.open_native(page, "operator")
                self.assertIn("ORGANIZER", page.locator("#ops-actor").inner_text())
                self.assertNotIn(
                    "ملاحظة داخلية لا تعرضها قائمة التشغيل", page.locator("body").inner_text()
                )
                proposal = page.locator(
                    f'#ops-lesson-catalog article[data-version="{self.version.pk}"] > form'
                )
                self.assertEqual(proposal.count(), 1)
                proposal.locator('[name="reason"]').fill("اقتراح بشري محفوظ من المنظم")
                proposal.locator('[name="start_ms"]').fill("10")
                proposal.locator('[name="end_ms"]').fill("100")
                self.assertTrue(proposal.evaluate("form => form.checkValidity()"))
                self.submit(page, proposal.locator("button"))
                self.assertEqual(page.locator("#ops-lesson-saved").count(), 1)
                self.assertEqual(page.locator("#ops-lesson-history > article").count(), 1)
                self.assertIn("ينتظر مراجعة", page.locator(".ops-link-state").inner_text())
                link_id = page.locator("#ops-lesson-history > article").get_attribute("data-link")
                self.screenshots(page, "organizer-proposed-exact-lesson")

                self.open_native(reviewer, "admin")
                self.assertIn("ORGANIZER_ADMIN", reviewer.locator("#ops-actor").inner_text())
                decision = reviewer.locator(
                    f'#ops-lesson-history article[data-link="{link_id}"] > form'
                )
                self.assertEqual(decision.count(), 1)
                decision.locator('[name="note"]').fill("مراجعة بشرية مستقلة للربط والموضع")
                decision.locator('[name="confirmed"]').check()
                self.submit(reviewer, decision.locator('button[value="APPROVE"]'))
                self.assertIn("اعتمده إنسان", reviewer.locator(".ops-link-state").inner_text())

                proposal = page.locator(
                    f'#ops-lesson-catalog article[data-version="{self.version.pk}"] > form'
                )
                proposal.locator('[name="reason"]').fill("اقتراح بعد سحب المنحة يجب رفضه")
                self.sync(lambda: self.authority.revoke(action="PROPOSE_LESSON_LINK"))
                self.submit(page, proposal.locator("button"), expected=409)

                decision = reviewer.locator(
                    f'#ops-lesson-history article[data-link="{link_id}"] > form'
                )
                decision.locator('[name="note"]').fill("سحب الرابط مع الاحتفاظ بتاريخ مراجعته")
                decision.locator('[name="confirmed"]').check()
                self.submit(reviewer, decision.locator('button[value="WITHDRAW"]'))
                self.assertIn("ربط مسحوب", reviewer.locator(".ops-link-state").inner_text())
                self.assertIn("admin", reviewer.locator("#ops-lesson-history").inner_text())
                self.screenshots(reviewer, "admin-withdrawn-link-history")
                self.assertEqual(self.sync(self.immutable_lesson_sources), self.lesson_originals)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                operator.tracing.stop(path=str(OUT / "operator-trace.zip"))
                admin.tracing.stop(path=str(OUT / "admin-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_roles": ["ORGANIZER", "ORGANIZER_ADMIN"],
                            "checks": [
                                "native organizer login and exact source lesson proposal form",
                                "pinned lesson version and bounded explicit recording span",
                                "native separate administrator review and preserved real actor history",
                                "revoked proposal grant rejected on already rendered form",
                                "native withdrawal keeps the proposal and review history",
                                "original evidence answer approval recording and metadata unchanged",
                            ],
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                if not (OUT / "operator-trace.zip").exists():
                    operator.tracing.stop(path=str(OUT / "operator-trace.zip"))
                if not (OUT / "admin-trace.zip").exists():
                    admin.tracing.stop(path=str(OUT / "admin-trace.zip"))
                operator.close()
                admin.close()
                browser.close()
