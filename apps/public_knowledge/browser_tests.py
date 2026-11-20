"""Protected Chromium: native human curation/review/release and anonymous reading.

Run only with the integrated dispatcher/menu and the browser sandbox enabled.
No success artifact is written until every asserted native journey finishes.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from .tests import FEATURES, CurationFixture

OUT = Path(".local/qa/functional-completion/public-browser")
BROWSER_FEATURES = {
    **FEATURES,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}


@override_settings(**BROWSER_FEATURES)
class PublicKnowledgeBrowserTests(CurationFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def form(self, page, action):
        form = page.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(form.count(), 1, f"Missing visible native action {action}")
        return form

    def submit(self, page, form, *, command=None):
        if isinstance(form, str):
            form = self.form(page, form)
        button = (
            form.locator(f'button[value="{command}"]')
            if command
            else form.locator("button:visible").first
        )
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.focus()
            button.press("Enter")
        self.assertIsNotNone(navigation.value)
        self.assertEqual(navigation.value.status, 200, page.locator("main").inner_text()[:1500])
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def login(self, page, subject):
        credential = {
            "editor": "synthetic-editor-credential-32-characters",
            "other": "synthetic-reviewer-credential-32-characters",
            "publisher": "synthetic-publisher-credential-32-characters",
        }[subject]
        page.goto(self.live_server_url + "/casework/staff/login/")
        page.locator("#credential").fill(credential)
        with page.expect_navigation(wait_until="domcontentloaded"):
            page.get_by_role("button", name="دخول المكتب", exact=True).click()
        self.submit(page, "open")
        self.submit(page, "pk_open")

    def review(self, page, record_id, command):
        self.submit(page, "pk_open")
        form = page.locator(f'article[data-public-record="{record_id}"] .pk-decision-form')
        form.locator('[name="note"]').fill("مراجعة بشرية اصطناعية للنسخة المختارة")
        form.locator('[name="confirmed"]').check()
        self.submit(page, form, command=command)

    def release(self, page, record_id):
        self.submit(page, "pk_open")
        form = page.locator(f'article[data-public-record="{record_id}"] .pk-release-form')
        form.locator('[name="confirmed"]').check()
        self.submit(page, form)

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_reviewed_profile_translation_release_and_revocation(self):
        from playwright.sync_api import sync_playwright

        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        external, errors, failures = [], [], []
        contexts = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )

            def route(r):
                parsed = urlsplit(r.request.url)
                if (
                    parsed.scheme != "http"
                    or parsed.netloc != urlsplit(self.live_server_url).netloc
                ):
                    external.append(r.request.url)
                    r.abort()
                else:
                    r.continue_()

            def new_page():
                context = browser.new_context(viewport={"width": 320, "height": 900})
                contexts.append(context)
                context.route("**/*", route)
                context.tracing.start(screenshots=True, snapshots=True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "response",
                    lambda response: (
                        failures.append(response.url) if response.status >= 400 else None
                    ),
                )
                return page

            try:
                editor, reviewer, publisher, reader = [new_page() for _ in range(4)]
                for page, subject in (
                    (editor, "editor"),
                    (reviewer, "other"),
                    (publisher, "publisher"),
                ):
                    self.login(page, subject)
                editor.locator("#pk-name").fill("عالم واجهة اصطناعي")
                editor.locator("#pk-bio").fill("")
                self.submit(editor, "pk_save_scholar")
                profile_id = editor.locator("article[data-public-record]").first.get_attribute(
                    "data-public-record"
                )
                reader.goto(self.live_server_url + "/library-preview/knowledge/")
                self.assertNotIn("عالم واجهة اصطناعي", reader.locator("main").inner_text())
                self.review(reviewer, profile_id, "REVIEW")
                self.review(publisher, profile_id, "APPROVE")
                reader.reload()
                self.assertNotIn("عالم واجهة اصطناعي", reader.locator("main").inner_text())
                self.release(publisher, profile_id)
                reader.reload()
                reader.get_by_role("link", name="عالم واجهة اصطناعي", exact=True).click()
                self.assertIn("عنوان تجريبي", reader.locator("main").inner_text())
                self.capture(reader, "reviewed-scholar")
                self.submit(editor, "pk_open")
                editor.locator("#pk-language").select_option("en")
                editor.locator("#pk-public-title").fill("Synthetic browser translation")
                editor.locator("#pk-question").fill("Explicit public synthetic question")
                editor.locator("#pk-translation").fill(
                    "Human reviewed browser translation, with unchanged Arabic original."
                )
                editor.locator("#pk-description").fill("Synthetic public description")
                editor.locator("#pk-author").select_option(profile_id)
                self.submit(editor, "pk_save_presentation")
                translation_id = (
                    editor.locator("article[data-public-record]")
                    .filter(has_text="Synthetic browser translation")
                    .first.get_attribute("data-public-record")
                )
                translated_url = (
                    self.live_server_url
                    + f"/library-preview/knowledge/publications/{self.edition['id']}/en/"
                )
                reader.goto(translated_url)
                self.assertIn("لا توجد ترجمة مراجعة", reader.locator("main").inner_text())
                self.assertIn("نص محرر مسموح", reader.locator("#public-answer").inner_text())
                self.review(reviewer, translation_id, "REVIEW")
                self.review(publisher, translation_id, "APPROVE")
                reader.reload()
                self.assertIn("لا توجد ترجمة مراجعة", reader.locator("main").inner_text())
                self.release(publisher, translation_id)
                reader.reload()
                self.assertEqual(
                    reader.locator('[itemprop="inLanguage"]').get_attribute("content"), "en"
                )
                self.assertIn(
                    "Human reviewed browser translation",
                    reader.locator("#public-answer").inner_text(),
                )
                self.assertEqual(reader.locator('[itemprop="translationOfWork"]').count(), 1)
                for value in (
                    self.receipt["public_ref"],
                    self.receipt["case_id"],
                    "PRIVATE",
                    "epoch-1",
                    "synthetic-publication-directory",
                ):
                    self.assertNotIn(value, reader.content())
                self.capture(reader, "reviewed-translation")
                reader.get_by_role("link", name="فتح الأصل العربي المحفوظ", exact=True).click()
                self.assertEqual(reader.locator("#public-answer").inner_text(), "نص محرر مسموح")
                self.assertEqual(
                    reader.locator('[itemprop="inLanguage"]').get_attribute("content"), "ar"
                )
                self.capture(reader, "preserved-arabic")
                self.capture(publisher, "explicit-release-history")
                revoke = publisher.locator(
                    f'article[data-public-record="{translation_id}"] .pk-revoke-form'
                )
                revoke.locator('[name="note"]').fill("إيقاف الإتاحة ضمن اختبار دورة العمل")
                revoke.locator('[name="confirmed"]').check()
                self.submit(publisher, revoke)
                reader.goto(translated_url)
                self.assertIn("لا توجد ترجمة مراجعة", reader.locator("main").inner_text())
                self.assertNotIn(
                    "Human reviewed browser translation", reader.locator("main").inner_text()
                )
                self.capture(reader, "revoked-translation-fallback")
                sitemap = reader.goto(
                    self.live_server_url + "/library-preview/knowledge/sitemap.xml"
                )
                self.assertEqual(sitemap.status, 200)
                self.assertNotIn(f"/{self.edition['id']}/en/", sitemap.text())
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                self.assertEqual(failures, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser": browser.version,
                            "sandbox": True,
                            "widths": [320, 1280],
                            "external_requests": external,
                            "page_errors": errors,
                            "http_failures": failures,
                            "independent_human_review": True,
                            "approval_requires_separate_release": True,
                            "arabic_original_preserved": True,
                            "revocation_hides_translation": True,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            finally:
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"trace-{index}.zip"))
                    context.close()
                browser.close()
