"""Protected native organizer queue; exact grants, current state and preserved originals."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .test_support import CREDENTIALS, FEATURES, OperationalFixture

OUT = Path(".local/qa/functional-continuation/operational-browser")


@override_settings(**FEATURES)
class OperationalWorkspaceBrowserTests(OperationalFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def run():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def submit(self, page, button, expected=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.focus()
            button.press("Enter")
        self.assertEqual(
            navigation.value.status, expected, page.locator("body").inner_text()[:1000]
        )
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_actual_organizer_queue_filters_and_scoped_details_without_scholarly_authority(self):
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
                self.assertEqual(
                    page.goto(self.live_server_url + "/casework/operations/login/").status, 200
                )
                page.locator('[name="credential"]').fill(CREDENTIALS["operator"])
                self.submit(page, page.locator("#ops-login button"))
                self.assertIn("ORGANIZER", page.locator("#ops-actor").inner_text())
                self.assertEqual(page.locator("#ops-queue > article").count(), 5)
                body = page.locator("body").inner_text()
                for key in ("hidden", "unscoped"):
                    self.assertNotIn(self.receipts[key]["public_ref"], body)
                self.screenshots(page, "native-operational-queue")
                counts = {
                    "metadata": 5,
                    "delivery": 1,
                    "publication": 1,
                    "transcript": 1,
                    "capability": 3,
                }
                for section, count in counts.items():
                    self.submit(page, page.locator(f'#ops-filters button[value="{section}"]'))
                    self.assertEqual(page.locator("#ops-queue > article").count(), count)
                    row = page.locator(
                        f'article[data-case-ref="{self.receipts[section]["public_ref"]}"]'
                    )
                    self.submit(page, row.locator(f'button[name="section"][value="{section}"]'))
                    self.assertEqual(
                        page.locator("#ops-detail").get_attribute("data-section"), section
                    )
                    self.assertEqual(
                        page.locator(
                            '[name="answer"], [value="APPROVE"], [value="publish"]'
                        ).count(),
                        0,
                    )
                    self.assertIn("ORGANIZER", page.locator("#ops-actor").inner_text())
                    if section == "transcript":
                        self.assertIn("مراجعة المعنى", page.locator("#ops-detail").inner_text())
                    if section == "delivery":
                        self.assertIn("فشل مسجل", page.locator("#ops-detail").inner_text())
                    self.screenshots(page, "detail-" + section)
                    self.submit(page, page.locator("#ops-back button"))
                self.sync(lambda: self.authority.revoke(action="READ_PUBLICATION"))
                self.submit(page, page.locator('#ops-filters button[value="publication"]'))
                self.assertEqual(page.locator("#ops-queue > article").count(), 0)
                self.assertEqual(
                    page.locator('[data-filter-count="publication"]').inner_text(), "0"
                )
                self.assertNotIn(
                    self.receipts["publication"]["public_ref"], page.locator("body").inner_text()
                )
                self.sync(lambda: self.revoke_identity())
                self.submit(page, page.locator('#ops-filters button[value="all"]'), expected=409)
                self.assertNotIn(
                    self.receipts["metadata"]["public_ref"], page.locator("body").inner_text()
                )
                self.assertEqual(self.sync(self.state), self.originals)
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
                            "visible_cases": 5,
                            "queue_lane_counts": counts,
                            "checks": [
                                "actual organizer login with an independent CSRF-bound session",
                                "native filters and exact per-action case details for all five lanes",
                                "real failed delivery pending publication and meaning-review transcript",
                                "current platform capability mismatch without sending or publishing",
                                "hidden case identifiers and unauthorized counts omitted",
                                "no scholarly answer or approval controls",
                                "current action revocation and identity revocation",
                                "original case answer source and delivery histories unchanged",
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
