"""Actual public/staff FT forms, explicit number disclosure and native withdrawal."""

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.public_answer_media.test_support import CREDENTIALS

from .reference_test_support import FEATURES, ReferenceFixture

OUT = Path(".local/qa/functional-continuation/fatwa-reference-browser")


@override_settings(**FEATURES)
class FatwaReferenceBrowserTests(ReferenceFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def execute():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(execute).result(timeout=30)

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            name = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / name), full_page=True)
            proof["screenshots"].append(name)

    def submit(self, page, form, status=200):
        self.assertEqual(form.count(), 1)
        button = form.locator("button")
        self.assertEqual(button.count(), 1)
        self.assertTrue(button.is_visible())
        self.assertTrue(form.evaluate("form => form.checkValidity()"))
        with page.expect_navigation(wait_until="domcontentloaded") as event:
            button.focus()
            button.press("Enter")
        self.assertEqual(event.value.status, status)
        return event.value

    def test_native_exact_ft_lookup_scoped_staff_open_explicit_public_number_and_withdrawal(self):
        from playwright.sync_api import sync_playwright

        key = uuid.uuid4().hex
        private = cases.intake_case(
            original_question="PRIVATE unlisted reference fixture",
            source_event_id=key,
            requester_id=key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        before = (
            list(Case.objects.order_by("pk").values()),
            list(AnswerRevision.objects.order_by("pk").values()),
        )
        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "page_errors": [],
            "external_requests": [],
            "screenshots": [],
            "traces": [],
            "native_actions": [],
            "observed_statuses": {},
        }
        contexts = []
        origin = self.live_server_url
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"],
                    headless=True,
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                try:

                    def local_only(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme != "http" or parsed.netloc != urlsplit(origin).netloc:
                            proof["external_requests"].append("blocked")
                            route.abort()
                        else:
                            route.continue_()

                    def page(name):
                        context = browser.new_context(viewport={"width": 320, "height": 780})
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((name, context))
                        tab = context.new_page()
                        tab.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return tab

                    public, staff = page("public"), page("staff")
                    self.assertEqual(public.goto(origin + "/library-preview/").status, 200)
                    self.capture(public, "reference-search", proof)
                    form = public.locator("#public-reference-lookup")
                    form.locator('[name="ref"]').fill(self.receipt["public_ref"])
                    self.submit(public, form)
                    self.assertEqual(
                        public.locator("#published-fatwa-reference").inner_text(),
                        self.receipt["public_ref"],
                    )
                    self.assertIn(self.publication.body, public.locator("main").inner_text())
                    self.assertNotIn("PRIVATE", public.locator("main").inner_text())
                    self.assertNotIn(self.receipt["case_id"], public.content())
                    self.assertEqual(urlsplit(public.url).path, "/library-preview/by-reference/")
                    proof["native_actions"].append(
                        "public_exact_ft_form_to_current_released_edition"
                    )
                    self.capture(public, "exact-public-reference", proof)

                    bodies = []
                    for reference in (private["public_ref"], "FT-2026-" + "F" * 20):
                        self.assertEqual(public.goto(origin + "/library-preview/").status, 200)
                        form = public.locator("#public-reference-lookup")
                        form.locator('[name="ref"]').fill(reference)
                        self.submit(public, form, 404)
                        body = public.locator("body").inner_text()
                        self.assertNotIn(reference, body)
                        self.assertNotIn("PRIVATE", body)
                        bodies.append(body)
                    self.assertEqual(*bodies)
                    proof["private_and_unknown_same_response"] = True

                    self.assertEqual(staff.goto(origin + "/casework/staff/login/").status, 200)
                    staff.locator('[name="credential"]').fill(CREDENTIALS["publisher"])
                    self.submit(staff, staff.locator("form").first)
                    form = staff.locator("#staff-reference-lookup")
                    form.locator('[name="case_ref"]').fill(self.receipt["public_ref"])
                    self.submit(staff, form)
                    self.assertEqual(
                        staff.locator("#selected-reference").inner_text(),
                        self.receipt["public_ref"],
                    )
                    proof["native_actions"].append(
                        "authenticated_exact_ft_form_to_same_canonical_case"
                    )
                    self.capture(staff, "scoped-staff-reference", proof)
                    form = staff.locator("#staff-reference-lookup")
                    form.locator('[name="case_ref"]').fill(private["public_ref"])
                    self.submit(staff, form, 403)
                    self.assertNotIn(private["public_ref"], staff.content())
                    self.assertNotIn("PRIVATE unlisted", staff.content())
                    proof["observed_statuses"]["unscoped_private_reference"] = 403

                    self.assertEqual(staff.goto(origin + "/casework/staff/").status, 200)
                    form = staff.locator("#staff-reference-lookup")
                    form.locator('[name="case_ref"]').fill(self.receipt["public_ref"])
                    self.submit(staff, form)
                    publication_form = staff.locator(
                        '.mufti-case-nav > form:has(> input[name="action"][value="pub_open"])'
                    )
                    self.submit(staff, publication_form)
                    withdrawal = staff.locator(
                        f'#publication-edition-{self.publication.pk} > form:has(> input[name="action"][value="pub_withdraw"])'
                    )
                    withdrawal.locator('[name="confirm"]').check()
                    self.submit(staff, withdrawal)
                    self.assertTrue(
                        self.sync(
                            lambda: self.publication.actions.filter(action="WITHDRAW").exists()
                        )
                    )
                    proof["native_actions"].append("current_publisher_explicit_native_withdrawal")
                    for path in (self.reference_url, self.detail_url):
                        self.assertEqual(public.goto(origin + path).status, 404)
                        self.assertNotIn(self.receipt["public_ref"], public.content())
                        self.assertNotIn(self.publication.body, public.content())
                    proof["observed_statuses"]["withdrawn_reference"] = 404
                    proof["observed_statuses"]["withdrawn_exact_detail"] = 404
                    self.assertEqual(
                        before,
                        self.sync(
                            lambda: (
                                list(Case.objects.order_by("pk").values()),
                                list(AnswerRevision.objects.order_by("pk").values()),
                            )
                        ),
                    )
                    proof["canonical_cases_and_answers_unchanged"] = True
                    self.assertEqual(proof["page_errors"], [])
                    self.assertEqual(proof["external_requests"], [])
                    proof["status"] = "PASS"
                finally:
                    for name, context in contexts:
                        filename = f"{name}-trace.zip"
                        context.tracing.stop(path=str(OUT / filename))
                        proof["traces"].append(filename)
                        context.close()
                    browser.close()
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
