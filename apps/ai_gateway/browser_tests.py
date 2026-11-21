"""One protected native journey, requiring real campaign wiring, never patched UI."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import AnswerRevision
from apps.precise_citations.models import CitationSet

from .models import CandidateBatch, GatewayOutcome
from .test_support import FEATURES, GatewayFixture

OUT = Path(".local/qa/functional-continuation/ai-citation-browser")


@override_settings(**{**FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class CitationGatewayBrowserTests(GatewayFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, function):
        def operation():
            close_old_connections()
            try:
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(operation).result(timeout=30)

    def submit(self, page, button):
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, 200, page.locator("body").inner_text()[:1000])

    def panel_submit(self, page, button, *, expected=200):
        previous = page.locator("#ai-citation-result").get_attribute("data-next-state")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/casework/ai-citations/")
                and response.request.method == "POST"
            )
        ) as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, expected, response.value.body()[:1000])
        if expected == 200:
            page.wait_for_function(
                "previous => { const state = document.querySelector('#ai-citation-result').dataset.nextState; return Boolean(state) && state !== previous; }",
                arg=previous,
            )
            self.assertIn("no-store", response.value.headers.get("cache-control", ""))
        else:
            page.locator('#ai-citation-result[data-run-status="UNAVAILABLE"]').wait_for()

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_candidates_original_human_handoff_failure_revocation_and_manual_citation(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected browser proof requires FATWA_BROWSER_SANDBOX=1")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, payloads = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 320, "height": 900})

            def route(request):
                address = urlsplit(request.request.url)
                if (
                    address.scheme != "http"
                    or address.netloc != urlsplit(self.live_server_url).netloc
                ):
                    external.append(request.request.url)
                    request.abort()
                else:
                    if (
                        address.path == "/casework/ai-citations/"
                        and request.request.method == "POST"
                    ):
                        payloads.append(parse_qs(request.request.post_data or ""))
                    request.continue_()

            context.route("**/*", route)
            context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator("#credential").fill("synthetic-editor-credential-32-characters")
                self.submit(page, page.get_by_role("button", name="دخول المكتب", exact=True))
                opener = page.locator(
                    f'form:visible:has([name="case_ref"][value="{self.receipt["public_ref"]}"]):has([name="action"][value="open"])'
                ).first
                self.submit(page, opener.locator("button").first)
                target = page.locator(
                    'form:visible:has([name="action"][value="precise_open"])'
                ).first
                self.submit(page, target.locator("button").first)
                # No monkeypatch supplies this panel: missing campaign wiring fails.
                self.assertEqual(
                    page.locator('#ai-citation-panel[data-ai-citation="enabled"]').count(), 1
                )
                draft = (
                    self.answer_text
                    + '\nمسودة حرفية <img src=x onerror="throw 1"> لا يرسلها المساعد.'
                )
                page.locator("#precise-text").fill(draft)
                page.locator("#precise-phrase").fill("عبارة محددة")
                page.locator("#ai-citation-query").fill("عبارة محددة")
                page.locator("#ai-citation-source").select_option(
                    "LIBRARY:" + self.material["version_id"]
                )
                page.locator("#ai-citation-end").fill("24")
                request_button = page.locator("#ai-citation-request button")
                self.panel_submit(page, request_button)
                self.assertEqual(page.locator("#precise-text").input_value(), draft)
                self.assertIn(
                    "موفر اختبار اصطناعي", page.locator("#ai-citation-result").inner_text()
                )
                self.panel_submit(
                    page, page.get_by_role("button", name="فتح النص الأصلي وموضعه", exact=True)
                )
                self.assertEqual(
                    page.locator("#ai-citation-original").text_content(), self.source_text
                )
                self.assertEqual(
                    page.locator("#ai-citation-original mark").text_content(), self.source_text[:12]
                )
                self.capture(page, "original-and-unsaved-draft")
                self.panel_submit(
                    page,
                    page.get_by_role("button", name="اختيار هذا الموضع للنموذج اليدوي", exact=True),
                )
                self.assertEqual(page.locator("#precise-start").input_value(), "0")
                self.assertEqual(page.locator("#precise-end").input_value(), "12")
                self.assertEqual(page.locator("#precise-text").input_value(), draft)
                self.assertEqual(self.sync(lambda: AnswerRevision.objects.count()), 0)

                self.ai_provider.error = RuntimeError("synthetic unavailable")
                self.panel_submit(page, request_button)
                self.assertEqual(
                    page.locator("#ai-citation-result").get_attribute("data-run-status"),
                    "PROVIDER_FAILED",
                )
                self.assertEqual(page.locator("#precise-text").input_value(), draft)
                self.ai_provider.error, self.ai_provider.raw = None, b'{"answer":"fabricated"}'
                self.panel_submit(page, request_button)
                self.assertEqual(
                    page.locator("#ai-citation-result").get_attribute("data-run-status"),
                    "OUTPUT_REJECTED",
                )
                self.ai_provider.raw = None
                with override_settings(FATWA_AI_CITATION_PROVIDER=None):
                    self.panel_submit(page, request_button)
                    self.assertEqual(
                        page.locator("#ai-citation-result").get_attribute("data-run-status"),
                        "PROVIDER_UNAVAILABLE",
                    )
                    self.assertEqual(page.locator("#precise-text").input_value(), draft)
                self.panel_submit(page, request_button)
                self.gateway_authority.denied.add(("PROCESS_CONTEXT", "LIBRARY"))
                self.panel_submit(
                    page,
                    page.get_by_role("button", name="فتح النص الأصلي وموضعه", exact=True),
                    expected=409,
                )
                self.assertEqual(page.locator("#ai-citation-result .ai-candidates").count(), 0)
                self.assertEqual(page.locator("#precise-text").input_value(), draft)
                self.gateway_authority.denied.clear()
                self.panel_submit(page, request_button)
                self.panel_submit(
                    page,
                    page.get_by_role("button", name="اختيار هذا الموضع للنموذج اليدوي", exact=True),
                )
                self.capture(page, "human-handoff")
                self.assertEqual(
                    self.sync(
                        lambda: (AnswerRevision.objects.count(), CitationSet.objects.count())
                    ),
                    (0, 0),
                )

                # The human's existing exact-occurrence editor remains the sole
                # path that can add a citation and explicitly save an answer.
                self.submit(page, page.locator('button[name="command"][value="find"]'))
                page.locator('#precise-compose [name="occurrence"]').nth(1).check()
                self.submit(page, page.locator('button[name="command"][value="add"]'))
                self.assertEqual(page.locator("#precise-text").input_value(), draft)
                page.locator('#precise-compose [name="confirmed"]').check()
                self.submit(page, page.locator('button[name="command"][value="save"]'))
                self.assertEqual(self.sync(lambda: AnswerRevision.objects.get().text), draft)
                self.assertEqual(self.sync(lambda: CitationSet.objects.count()), 1)
                self.assertTrue(payloads)
                self.assertTrue(
                    all(
                        set(value)
                        <= {
                            "action",
                            "state",
                            "csrfmiddlewaretoken",
                            "query",
                            "selection",
                            "start",
                            "end",
                        }
                        for value in payloads
                    )
                )
                self.assertTrue(all("text" not in value for value in payloads))
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                outcomes = self.sync(
                    lambda: sorted(set(GatewayOutcome.objects.values_list("status", flat=True)))
                )
                self.assertEqual(
                    outcomes,
                    ["OUTPUT_REJECTED", "PROVIDER_FAILED", "PROVIDER_UNAVAILABLE", "SUCCEEDED"],
                )
                self.assertGreater(self.sync(lambda: CandidateBatch.objects.count()), 0)
                context.tracing.stop(path=str(OUT / "native-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        dict(
                            status="PASS",
                            sandbox=True,
                            widths=[320, 1280],
                            provider_mode="SYNTHETIC",
                            real_provider_quality="NOT_EVALUATED",
                            page_errors=errors,
                            external_requests=external,
                            checks=[
                                "real campaign wiring",
                                "independent processing grants",
                                "exact original text",
                                "unsaved draft retained",
                                "provider payload excludes answer draft",
                                "explicit human source handoff",
                                "provider unavailable failure and rejected output",
                                "current revocation removes candidate",
                                "manual citation path alone saves answer",
                                "native keyboard and RTL layouts",
                            ],
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                context.close()
                browser.close()
