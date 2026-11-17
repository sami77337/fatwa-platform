"""Real mobile/desktop requester journey; all providers and files are synthetic."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import connections
from django.test import LiveServerTestCase, override_settings

from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import services as cases
from apps.private_media.fixtures import synthetic_files

from .test_support import PORTAL_SETTINGS, PortalFixture

OUT = Path(".local/qa/v11-requester/browser")


@override_settings(**PORTAL_SETTINGS)
class PortalBrowserTests(PortalFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_connected_requester_phone_files_audio_citations_delivery_and_stale_denial(self):
        from playwright.sync_api import sync_playwright

        png = next(item for item in synthetic_files() if item[1] == "image/png")
        errors, external = [], []
        OUT.mkdir(parents=True, exist_ok=True)

        def work(fn):
            # Playwright sync API has a running event loop: database work remains
            # on a separate synchronous connection and every worker closes it.
            def run():
                try:
                    return fn()
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(run).result()

        def clarify():
            current = cases.read_case(**self.staff())
            cases.request_clarification(
                **self.staff(),
                text="وضح السؤال الاصطناعي",
                expected_revision=current["revision"],
                expected_evidence_version=current["evidence_version"],
            )

        def cited_draft():
            edition = source_fixture()
            source = citations.read_source(**self.staff(), edition_id=edition, source_row_id=2)
            current = cases.read_case(**self.staff())
            citations.save_cited_answer(
                **self.staff(),
                text="HIDDEN_DRAFT_NOT_FOR_REQUESTER",
                expected_revision=current["revision"],
                expected_evidence_version=current["evidence_version"],
                selections=[
                    dict(
                        edition_id=edition,
                        source_row_id=2,
                        source_sha256=source["source_sha256"],
                        editorial_note="HIDDEN_RESEARCH_NOTE",
                    )
                ],
            )

        with sync_playwright() as p:
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            try:
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route(r):
                    if urlsplit(r.request.url).netloc != urlsplit(self.live_server_url).netloc:
                        external.append(r.request.url)
                        r.abort()
                    else:
                        r.continue_()

                context.route("**/*", route)

                def click(name, keyboard=False):
                    button = page.get_by_role("button", name=name, exact=True)
                    with page.expect_navigation(wait_until="domcontentloaded") as navigation:
                        if keyboard:
                            button.focus()
                            button.press("Enter")
                        else:
                            button.click()
                    self.assertEqual(navigation.value.status, 200)
                    self.assertIn("no-store", navigation.value.headers["cache-control"])

                def refresh():
                    response = page.goto(self.live_server_url + "/casework/status/")
                    self.assertEqual(response.status, 200)
                    self.assertNotIn("HIDDEN_DRAFT_NOT_FOR_REQUESTER", page.content())
                    self.assertNotIn("HIDDEN_RESEARCH_NOTE", page.content())
                    self.assertNotIn("synthetic-mufti", page.content())

                refresh()
                page.locator("#portal-token").fill(self.a["token"])
                click("فتح قضيتي", keyboard=True)
                self.assertIn("سؤال اصطناعي حرفي", page.content())
                page.locator("#portal-attachment").set_input_files(
                    {
                        "name": png[0],
                        "mimeType": png[1],
                        "buffer": png[2],
                    }
                )
                page.locator('form:has(#portal-attachment) [name="synthetic_only"]').check()
                click("حفظ مرفق السؤال")
                image = page.locator("#attachments img")
                image.scroll_into_view_if_needed()
                image.evaluate("img => img.decode()")
                self.assertEqual(
                    image.evaluate("img => [img.naturalWidth,img.naturalHeight]"), [16, 12]
                )
                work(clarify)
                refresh()
                self.assertIn("وضح السؤال الاصطناعي", page.content())
                page.locator("#portal-followup").fill("رد السائل الاصطناعي من الهاتف")
                page.locator("#reply-attachment").set_input_files(
                    {
                        "name": "clarification.txt",
                        "mimeType": "text/plain",
                        "buffer": b"synthetic clarification attachment",
                    }
                )
                page.locator('#portal-reply-form [name="synthetic_only"]').check()
                click("إرسال التعقيب", keyboard=True)
                self.assertIn("حُفظ ردك ومرفقه معًا", page.content())
                self.assertIn("رد السائل الاصطناعي من الهاتف", page.content())
                self.assertIn("clarification.txt", page.content())
                self.assertEqual(page.locator('[data-history-kind="attachment"]').count(), 2)
                work(cited_draft)
                refresh()
                self.assertEqual(
                    page.locator("[data-answer-state]").get_attribute("data-answer-state"),
                    "UNDER_REVIEW",
                )
                work(self.approve)
                refresh()
                self.assertEqual(
                    page.locator("[data-answer-state]").get_attribute("data-answer-state"),
                    "APPROVED_UNAVAILABLE",
                )
                work(self.release)
                refresh()
                self.assertEqual(
                    page.locator("[data-answer-state]").get_attribute("data-answer-state"),
                    "PRIVATE_AVAILABLE",
                )
                self.assertIn("فَرْعٌ تَجْرِيبِيّ", page.content())
                self.assertIn("طبعة اختبار", page.content())
                audio = page.locator("#answer audio")
                audio.scroll_into_view_if_needed()
                audio.evaluate("async audio => { await audio.play(); }")
                self.assertTrue(audio.evaluate("audio => !audio.paused || audio.ended"))
                self.assertAlmostEqual(audio.evaluate("audio => audio.duration"), 0.1, places=2)
                file_link = page.get_by_role("link", name="فتح جزء الجواب 2", exact=True)
                old_part_url = file_link.get_attribute("href")
                file_response = context.request.get(self.live_server_url + old_part_url)
                self.assertEqual(file_response.status, 200)
                self.assertEqual(file_response.body(), b"synthetic file")
                work(self.stage)

                def accept():
                    lease = self.reserve()
                    part = self.resolve(lease)
                    self.outcome(lease, part, "ACCEPTED")
                    return lease, part

                lease, part = work(accept)
                refresh()
                self.assertEqual(
                    page.locator("[data-delivery-state]").get_attribute("data-delivery-state"),
                    "PROVIDER_ACCEPTED",
                )

                def deliver():
                    self.outcome(lease, part, "DELIVERED")
                    while remaining := self.reserve():
                        self.outcome(remaining, self.resolve(remaining), "DELIVERED")

                work(deliver)
                refresh()
                self.assertEqual(
                    page.locator("[data-delivery-state]").get_attribute("data-delivery-state"),
                    "SIGNED_DELIVERED",
                )
                self.assertIn("3 / 3", page.content())
                for width in (320, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    page.screenshot(path=str(OUT / f"portal-{width}.png"), full_page=True)
                page.locator("#portal-followup").fill("وقائع جديدة تبطل الجواب السابق")
                click("إرسال التعقيب")
                self.assertEqual(page.locator("#authorized-answer").count(), 0)
                self.assertEqual(page.locator("#answer audio").count(), 0)
                self.assertEqual(
                    context.request.get(self.live_server_url + old_part_url).status, 404
                )
                work(lambda: cases.revoke_access(**self.staff(), requester_id="requester-a"))
                refresh()
                self.assertEqual(page.locator("#portal-token").count(), 1)
                self.assertNotIn("وقائع جديدة تبطل الجواب السابق", page.content())
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "rtl_widths": [320, 1280],
                            "keyboard_submit": True,
                            "atomic_clarification_with_file": True,
                            "image_dimensions": [16, 12],
                            "audio_duration": 0.1,
                            "signed_parts": "3/3",
                            "stale_part_http": 404,
                            "external_requests": external,
                            "page_errors": errors,
                            "read_confirmation": False,
                        },
                        indent=2,
                    )
                )
            finally:
                browser.close()
