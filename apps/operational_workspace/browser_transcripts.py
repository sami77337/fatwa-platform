"""One protected native journey through actual editor, editorial reviewer and Mufti."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from . import browser_tests
from .test_support import CREDENTIALS
from .transcript_test_support import TEXT, TRANSCRIPT_FEATURES, TranscriptFixture

OUT = Path(".local/qa/functional-continuation/operational-transcripts-browser")


@override_settings(**TRANSCRIPT_FEATURES)
class OperationalTranscriptsBrowserTests(TranscriptFixture, LiveServerTestCase):
    host = "127.0.0.1"
    sync = browser_tests.OperationalWorkspaceBrowserTests.sync
    submit = browser_tests.OperationalWorkspaceBrowserTests.submit

    def open_editor(self, page):
        page.locator("#ops-transcripts-index > summary").click()
        entry = page.locator(
            f'#ops-transcripts-index form[data-case-ref="{self.target["public_ref"]}"]'
        )
        self.assertEqual(entry.count(), 1)
        self.submit(page, entry.locator("button"))

    def login_native(self, page, subject):
        base = self.live_server_url + "/casework/operations/"
        self.assertEqual(page.goto(base + "login/").status, 200)
        page.locator('[name="credential"]').fill(CREDENTIALS[subject])
        self.submit(page, page.locator("#ops-login button"))
        self.open_editor(page)

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_native_organizer_transcript_admin_review_and_mufti_meaning_approval_keep_original(
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
                for subject in ("operator", "admin", "mufti")
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
                operator, admin, mufti = (pages[key] for key in ("operator", "admin", "mufti"))
                self.login_native(operator, "operator")
                self.assertIn("ORGANIZER", operator.locator("#ops-actor").inner_text())
                editor = operator.locator(".ops-transcript-save")
                self.assertEqual(editor.count(), 1)
                editor.locator('[name="text"]').fill(TEXT)
                editor.locator('[name="note"]').fill("تفريغ بشري من المنظم مع حفظ الأصل")
                editor.locator(".ops-transcript-segments > summary").click()
                editor.locator('[name="quote_0"]').fill(TEXT[:6])
                editor.locator('[name="start_ms_0"]').fill("10")
                editor.locator('[name="end_ms_0"]').fill("100")
                self.assertTrue(editor.evaluate("form => form.checkValidity()"))
                self.submit(operator, editor.locator("button"))
                self.assertEqual(operator.locator("#ops-transcript-history > article").count(), 1)
                self.assertIn(TEXT, operator.locator("#ops-transcript-history").inner_text())
                self.screenshots(operator, "organizer-editorial-version")

                self.login_native(admin, "admin")
                decision = admin.locator(".ops-transcript-decision")
                decision.locator('[name="note"]').fill("مراجعة مستقلة تحفظ معنى الأصل")
                decision.locator('[name="confirmed"]').check()
                self.submit(admin, decision.locator('button[value="REVIEW"]'))
                self.assertEqual(admin.locator('[data-decision="REVIEW"]').count(), 1)

                editor = operator.locator(".ops-transcript-save")
                editor.locator('[name="text"]').fill(TEXT + " تحرير يستلزم نظر المفتي.")
                editor.locator('[name="change_kind"]').select_option("MEANING_REVIEW")
                editor.locator('[name="note"]').fill("إحالة مراجعة المعنى إلى المفتي المخول")
                self.submit(operator, editor.locator("button"))
                self.assertEqual(operator.locator("#ops-transcript-history > article").count(), 2)
                self.assertEqual(operator.locator('button[value="APPROVE_MEANING"]').count(), 0)
                self.submit(admin, admin.locator("#ops-transcripts-back button"))
                self.open_editor(admin)
                self.assertEqual(admin.locator('button[value="APPROVE_MEANING"]').count(), 0)

                self.login_native(mufti, "mufti")
                self.assertIn("MUFTI", mufti.locator("#ops-actor").inner_text())
                meaning = mufti.locator("#ops-transcript-history > article").nth(1).locator("form")
                meaning.locator('[name="note"]').fill("اعتماد مستقل للمعنى من مفتي فعلي")
                meaning.locator('[name="confirmed"]').check()
                self.submit(mufti, meaning.locator('button[value="APPROVE_MEANING"]'))
                self.assertEqual(mufti.locator('[data-decision="APPROVE_MEANING"]').count(), 1)
                self.screenshots(mufti, "mufti-meaning-review-history")

                editor = operator.locator(".ops-transcript-save")
                editor.locator('[name="note"]').fill("تحرير بعد سحب المنحة يجب رفضه")
                self.sync(lambda: self.authority.revoke(action="EDIT_RECORDING_TRANSCRIPT"))
                self.submit(operator, editor.locator("button"), expected=409)

                self.submit(admin, admin.locator("#ops-transcripts-back button"))
                self.open_editor(admin)
                decision = admin.locator("#ops-transcript-history > article").nth(1).locator("form")
                decision.locator('[name="note"]').fill("سحب النسخة مع حفظ المراجعة العلمية")
                decision.locator('[name="confirmed"]').check()
                self.submit(admin, decision.locator('button[value="WITHDRAW"]'))
                self.assertEqual(admin.locator('[data-decision="WITHDRAW"]').count(), 1)
                self.assertEqual(admin.locator('[data-decision="APPROVE_MEANING"]').count(), 1)
                self.assertEqual(
                    self.sync(self.immutable_transcript_sources), self.transcript_originals
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
                            "actual_roles": ["ORGANIZER", "ORGANIZER_ADMIN", "MUFTI"],
                            "checks": [
                                "native organizer creates source-pinned editorial transcript and explicit segment",
                                "native separate administrator records independent editorial review",
                                "organizer and administrator cannot approve meaning despite permissive test grants",
                                "native actual Mufti separately approves meaning on exact new version",
                                "withdrawal preserves the editor reviewer and meaning approval history",
                                "revoked editor grant rejects already rendered form",
                                "source answer approval and recording bytes remain unchanged",
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
