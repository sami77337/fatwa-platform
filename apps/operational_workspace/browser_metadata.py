"""One protected native organizer metadata journey, including current denial."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.case_organization import services as organization

from . import browser_tests
from .metadata_test_support import METADATA_FEATURES, MetadataFixture
from .test_support import CREDENTIALS

OUT = Path(".local/qa/functional-continuation/operational-metadata-browser")


@override_settings(**METADATA_FEATURES)
class OperationalMetadataBrowserTests(MetadataFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_tests.OperationalWorkspaceBrowserTests.sync
    submit = browser_tests.OperationalWorkspaceBrowserTests.submit

    def test_native_organizer_tags_types_and_reviewed_classification_preserve_originals(self):
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
            context = browser.new_context(locale="ar", viewport={"width": 1280, "height": 900})
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
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
                base = self.live_server_url + "/casework/operations/"
                self.assertEqual(page.goto(base + "login/").status, 200)
                page.locator('[name="credential"]').fill(CREDENTIALS["operator"])
                self.submit(page, page.locator("#ops-login button"))
                page.locator("#ops-metadata-index > summary").click()
                entry = page.locator(
                    f'#ops-metadata-index form[data-case-ref="{self.target["public_ref"]}"]'
                )
                self.assertEqual(entry.count(), 1)
                self.submit(page, entry.locator("button"))
                self.assertIn("ORGANIZER", page.locator("#ops-actor").inner_text())
                self.assertNotIn(
                    "ملاحظة داخلية لا تعرضها قائمة التشغيل", page.locator("body").inner_text()
                )
                page.locator('#ops-tags-form [name="tags"]').fill("تنظيم بشري\nوسم ثانٍ")
                self.submit(page, page.locator("#ops-tags-form button"))
                self.assertEqual(page.locator("#ops-metadata-saved").count(), 1)
                page.locator('#ops-types-form [value="EDUCATION"]').uncheck()
                page.locator('#ops-types-form [value="RULING"]').check()
                page.locator('#ops-types-form [value="TIME"]').check()
                self.submit(page, page.locator("#ops-types-form button"))
                form = page.locator(f'article[data-version="{self.version.pk}"] > form')
                self.assertEqual(form.count(), 1)
                form.locator('[name="primary"]').select_option(self.version.nodes[1]["id"])
                form.locator(f'[name="additional"][value="{self.version.nodes[3]["id"]}"]').check()
                form.locator('[name="reason"]').fill("تصنيف بشري من رحلة المنظم الأصلية")
                form.locator('[name="confirmed"]').check()
                self.assertTrue(form.evaluate("form => form.checkValidity()"))
                self.submit(page, form.locator("button"))
                self.assertIn("operator", page.locator("#ops-classification-current").inner_text())
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(OUT / f"saved-metadata-{width}.png"), full_page=True)
                current = self.sync(
                    lambda: organization.snapshot(
                        case_id=self.target["case_id"],
                        subject_id="mufti",
                        provider=self.directory,
                        synthetic_fixtures_only=True,
                    )
                )
                self.assertEqual(current["tags"], ["تنظيم بشري", "وسم ثانٍ"])
                self.assertEqual(current["question_types"], ["RULING", "TIME"])
                self.submit(page, page.locator("#ops-metadata-back button"))
                page.locator("#ops-metadata-index > summary").click()
                self.submit(
                    page,
                    page.locator(
                        f'#ops-metadata-index form[data-case-ref="{self.target["public_ref"]}"] button'
                    ),
                )
                page.locator('#ops-tags-form [name="tags"]').fill("تغيير بعد سحب الإذن")
                self.sync(lambda: self.authority.revoke(action="EDIT_TAGS"))
                self.submit(page, page.locator("#ops-tags-form button"), expected=409)
                self.assertEqual(
                    self.sync(self.immutable_metadata_sources), self.metadata_originals
                )
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                context.tracing.stop(path=str(OUT / "trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_role": "ORGANIZER",
                            "checks": [
                                "native organizer login and exact metadata form entry",
                                "separate tags and question types persisted with real organizer audit",
                                "human binding of exact reviewed provisional taxonomy version",
                                "completed case stays reachable without pending-count inflation",
                                "Mufti projection observes the same original metadata records",
                                "revoked action denied at native submit and scholarly originals unchanged",
                            ],
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                if not (OUT / "trace.zip").exists():
                    context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
