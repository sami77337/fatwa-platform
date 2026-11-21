"""Protected native browser journey; no success artifact until every check passes."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .models import CollectionRevision
from .test_support import FEATURES, CollectionFixture

OUT = Path(".local/qa/functional-continuation/collections-browser")
BROWSER_FEATURES = {
    **FEATURES,
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_MUFTI_WORKSPACE_ENABLED": True,
}


@override_settings(**BROWSER_FEATURES)
class PublicCollectionsBrowserTests(CollectionFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        """Evaluate ORM work off Playwright's event-loop thread and close its connection."""

        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as workers:
            return workers.submit(work).result(timeout=30)

    def form(self, page, action):
        result = page.locator(f'form:visible:has([name="action"][value="{action}"])').first
        self.assertEqual(result.count(), 1, f"Missing visible native action {action}")
        return result

    def submit(self, page, form, command=None):
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
        self.assertEqual(navigation.value.status, 200, page.locator("main").inner_text()[:1200])
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
        opener = page.locator(
            f'form:visible:has([name="case_ref"][value="{self.receipt["public_ref"]}"]):has([name="action"][value="open"])'
        ).first
        self.submit(page, opener)
        self.submit(page, "pc_open")

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def act(self, page, identifier, action):
        self.submit(page, "pc_open")
        selector = (
            ".pc-release"
            if action == "RELEASE"
            else ".pc-revoke"
            if action == "REVOKE"
            else ".pc-decision"
        )
        form = page.locator(f'article[data-pc-record="{identifier}"] {selector}')
        if action != "RELEASE":
            form.locator('[name="note"]').fill("قرار مراجعة اصطناعي مستقل عبر الواجهة")
        form.locator('[name="confirmed"]').check()
        self.submit(
            page, form, command=action if action in {"REVIEW", "APPROVE", "WITHDRAW"} else None
        )

    def test_cross_case_native_curation_order_review_release_and_revocation(self):
        from playwright.sync_api import sync_playwright

        _, second = self.second_publication()
        material = self.library_record(title="مصدر منتقى عبر الواجهة")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, contexts = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get(
                    "FATWA_BROWSER_EXECUTABLE",
                    os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                ),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )

            def new_page():
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
                return page

            try:
                author, reviewer, publisher, reader = [new_page() for _ in range(4)]
                for page, subject in (
                    (author, "editor"),
                    (reviewer, "other"),
                    (publisher, "publisher"),
                ):
                    self.login(page, subject)
                form = self.form(author, "pc_save")
                form.locator('[name="kind"]').select_option("TOPIC")
                form.locator('[name="title"]').fill("موضوع عابر للقضايا عبر الواجهة")
                form.locator('[name="introduction"]').fill(
                    "مقدمة منتقاة بشرية؛ لا تجمع الأحكام في جواب جديد."
                )
                form.locator('[name="featured"]').check()
                selections = self.sync(
                    lambda: (
                        self.member(),
                        self.member(second),
                        f"LIBRARY|{material['version_id']}|{material['digest']}",
                    )
                )
                for selection in selections:
                    form.locator(f'[name="members"][value="{selection}"]').check()
                self.submit(author, form)
                first = self.sync(lambda: CollectionRevision.objects.values("id").get())
                self.capture(author, "draft")
                # Real native reorder creates another immutable draft.
                reorder = author.locator(
                    'form:visible:has([name="action"][value="pc_reorder"]):has([name="index"][value="1"])'
                )
                self.submit(author, reorder, command="UP")
                record = self.sync(
                    lambda: (
                        CollectionRevision.objects.order_by("-number")
                        .values("id", "number", "series__public_id")
                        .first()
                    )
                )
                self.assertEqual(record["number"], 2)
                self.assertNotEqual(record["id"], first["id"])
                public_url = (
                    self.live_server_url
                    + f"/library-preview/collections/items/{record['series__public_id']}/"
                )
                self.assertEqual(reader.goto(public_url).status, 404)
                self.act(reviewer, str(record["id"]), "REVIEW")
                self.act(publisher, str(record["id"]), "APPROVE")
                self.assertEqual(reader.goto(public_url).status, 404)
                self.act(publisher, str(record["id"]), "RELEASE")
                self.assertEqual(reader.goto(public_url).status, 200)
                self.assertIn("فتوى ثانية مصرح بها", reader.locator("main").inner_text())
                self.assertIn("مصدر منتقى عبر الواجهة", reader.locator("main").inner_text())
                self.assertNotIn("PRIVATE", reader.locator("body").inner_text())
                self.assertNotIn(self.receipt["public_ref"], reader.locator("body").inner_text())
                members = reader.locator(".pc-members h3").all_text_contents()
                self.assertEqual(members[0], "فتوى ثانية مصرح بها")
                self.capture(reader, "released")
                self.assertEqual(
                    reader.goto(self.live_server_url + "/library-preview/collections/").status, 200
                )
                reader.locator("#pc-q").fill("موضوع عابر")
                self.submit(reader, reader.locator('form[role="search"]'))
                self.assertIn("موضوع عابر للقضايا", reader.locator("main").inner_text())
                self.capture(reader, "filtered")
                self.act(publisher, str(record["id"]), "REVOKE")
                self.assertEqual(reader.goto(public_url).status, 404)
                self.assertEqual(
                    reader.goto(self.live_server_url + "/library-preview/collections/").status, 200
                )
                self.assertNotIn("موضوع عابر للقضايا", reader.locator("main").inner_text())
                self.assertEqual(self.sync(lambda: CollectionRevision.objects.count()), 2)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"trace-{index}.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "journey": "native cross-case selection, reorder, independent review/approval, explicit release, query, revocation",
                            "independent_staff_contexts": 3,
                            "anonymous_contexts": 1,
                            "external_requests": external,
                            "page_errors": errors,
                            "browser": browser.version,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
            finally:
                for context in contexts:
                    context.close()
                browser.close()
