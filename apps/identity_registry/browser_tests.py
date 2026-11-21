"""Protected native capture/verification/merge/split/revocation journey."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import Case, CaseSource
from apps.source_case_intake.models import SourceReceipt

from .boundary import digest
from .models import IdentityMembership, RegistryOperation
from .test_support import FEATURES, RegistryFixture

OUT = Path(".local/qa/functional-continuation/identities-browser")


@override_settings(**{**FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class IdentityRegistryBrowserTests(RegistryFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(work).result(timeout=30)

    def originals(self):
        return digest(
            [
                list(Case.objects.order_by("pk").values()),
                list(CaseSource.objects.order_by("pk").values()),
                [
                    (str(row.pk), bytes(row.raw).hex())
                    for row in SourceReceipt.objects.order_by("pk")
                ],
            ]
        )

    def submit(self, page, button, expected=200):
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, expected, page.locator("body").inner_text()[:1200])
        self.assertIn("no-store", response.value.headers.get("cache-control", ""))

    def open_case(self, page, receipt):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 200)
        opener = page.locator(
            f'form:visible:has([name="case_ref"][value="{receipt["public_ref"]}"]):has([name="action"][value="open"])'
        ).first
        self.submit(page, opener.locator("button").first)
        target = page.locator('form:visible:has([name="action"][value="ir_open"])').first
        self.assertEqual(target.count(), 1)
        self.submit(page, target.locator("button").first)

    def login(self, page, subject):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/login/").status, 200)
        name = {"editor": "editor", "other": "reviewer"}[subject]
        page.locator("#credential").fill(f"synthetic-{name}-credential-32-characters")
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            page.get_by_role("button", name="دخول المكتب", exact=True).click()
        self.assertEqual(response.value.status, 200)

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def create_person(self, page, label):
        form = page.locator("#ir-person")
        form.locator('[name="label"]').fill(label)
        form.locator('[name="reason"]').fill("وصف شخص داخلي اصطناعي؛ ليس اسمًا مدنيًا موثقًا")
        form.locator('[name="confirmed"]').check()
        self.submit(page, form.locator("button"))
        return (
            page.locator('#ir-prepare [name="target_person_id"] option')
            .filter(has_text=label)
            .get_attribute("value")
        )

    def propose(self, page, identity, person):
        form = page.locator(f'[data-ir-identity="{identity}"] .ir-propose')
        form.locator('[name="person_id"]').select_option(person)
        form.locator('[name="evidence"]').fill(
            "سند بشري اصطناعي مستقل؛ لا اعتماد على الاسم المتشابه"
        )
        form.locator('[name="confirmed"]').check()
        self.submit(page, form.locator("button"))
        self.assertIn(
            "بانتظار تحقق مستقل", page.locator(f'[data-ir-identity="{identity}"]').inner_text()
        )
        self.assertEqual(page.locator(f'[data-ir-identity="{identity}"] .ir-verify').count(), 0)

    def verify(self, page, receipt, identity):
        self.open_case(page, receipt)
        form = page.locator(f'[data-ir-identity="{identity}"] .ir-verify')
        form.locator('[name="reason"]').fill("تحقق بشري مستقل من السند الاصطناعي")
        form.locator('[name="confirmed"]').check()
        self.submit(page, form.locator('button[value="VERIFY"]'))
        self.assertIn(
            "ربط تحقّق منه إنسان مستقل",
            page.locator(f'[data-ir-identity="{identity}"]').inner_text(),
        )

    def test_native_independent_identity_states_and_reviewable_merge_split(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected browser proof requires FATWA_BROWSER_SANDBOX=1")
        other_case, _ = self.new_case()
        original = self.originals()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, contexts = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )

            def page():
                context = browser.new_context(viewport={"width": 320, "height": 900})
                contexts.append(context)

                def route(request):
                    target = urlsplit(request.request.url)
                    if (
                        target.scheme != "http"
                        or target.netloc != urlsplit(self.live_server_url).netloc
                    ):
                        external.append(request.request.url)
                        request.abort()
                    else:
                        request.continue_()

                context.route("**/*", route)
                context.tracing.start(screenshots=True, snapshots=True)
                result = context.new_page()
                result.on("pageerror", lambda error: errors.append(str(error)))
                return result

            try:
                author, reviewer = page(), page()
                self.login(author, "editor")
                self.login(reviewer, "other")
                self.open_case(author, self.receipt)
                self.submit(author, author.locator("#ir-capture button"))
                first = author.locator("[data-ir-identity]").get_attribute("data-ir-identity")
                person_a = self.create_person(author, "الشخص الألف الاصطناعي")
                self.propose(author, first, person_a)
                self.screenshots(author, "proposed")
                self.verify(reviewer, self.receipt, first)
                self.open_case(author, other_case)
                self.submit(author, author.locator("#ir-capture button"))
                second = next(
                    value
                    for value in author.locator("[data-ir-identity]").evaluate_all(
                        "nodes => nodes.map(node => node.dataset.irIdentity)"
                    )
                    if value != first
                )
                person_b = self.create_person(author, "الشخص الباء الاصطناعي")
                self.propose(author, second, person_b)
                self.verify(reviewer, other_case, second)
                self.open_case(author, self.receipt)
                form = author.locator("#ir-prepare")
                form.locator('[name="kind"]').select_option("MERGE")
                form.locator('[name="source_person_id"]').select_option(person_b)
                form.locator('[name="target_person_id"]').select_option(person_a)
                self.submit(author, form.locator("button"))
                self.assertIn(other_case["public_ref"], author.locator("#ir-preview").inner_text())
                self.assertEqual(self.sync(lambda: IdentityMembership.objects.count()), 2)
                self.screenshots(author, "merge-preview")
                form = author.locator("#ir-apply")
                form.locator('[name="reason"]').fill("تصحيح دمج روابط موثق بعد المعاينة")
                form.locator('[name="confirmed"]').check()
                self.submit(author, form.locator("button"))
                form = author.locator("#ir-prepare")
                form.locator('[name="kind"]').select_option("SPLIT")
                form.locator('[name="source_person_id"]').select_option(person_a)
                form.locator('[name="target_person_id"]').select_option(person_b)
                form.locator(f'[name="identity_ids"][value="{second}"]').check()
                self.submit(author, form.locator("button"))
                form = author.locator("#ir-apply")
                form.locator('[name="reason"]').fill("تصحيح فصل الرابط المحدد مع حفظ كل السوابق")
                form.locator('[name="confirmed"]').check()
                self.submit(author, form.locator("button"))
                form = author.locator(f'[data-ir-identity="{second}"] .ir-unlink')
                form.locator('[name="reason"]').fill("سحب التحقق بعد إعادة فحص السند")
                form.locator('[name="confirmed"]').check()
                self.submit(author, form.locator("button"))
                self.assertIn(
                    "غير مرتبطة", author.locator(f'[data-ir-identity="{second}"]').inner_text()
                )
                self.screenshots(author, "split-and-revoked")
                self.assertEqual(
                    self.sync(
                        lambda: list(
                            RegistryOperation.objects.order_by("created_at").values_list(
                                "kind", flat=True
                            )
                        )
                    ),
                    ["VERIFY", "VERIFY", "MERGE", "SPLIT", "UNLINK"],
                )
                self.assertEqual(self.sync(self.originals), original)
                self.sync(lambda: self.authority.denied.add("READ"))
                self.submit(author, author.locator("#ir-search button"), expected=409)
                self.assertNotIn("الشخص الألف الاصطناعي", author.locator("body").inner_text())
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"actor-{index}-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "independent_humans": 2,
                            "checks": [
                                "native exact-source capture",
                                "proposed independently verified and revoked states",
                                "signed merge and selected split previews",
                                "append-only audit and unchanged originals",
                                "current reader revocation",
                            ],
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for context in contexts:
                    context.close()
                browser.close()
