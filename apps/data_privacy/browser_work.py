"""A human answer remains possible while classification is explicitly pending."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.db import close_old_connections, connection, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvidence, CaseSource
from apps.operational_workspace.test_support import CREDENTIALS

from .campaign_test_support import FEATURES
from .models import ClassificationRevision
from .private_work_test_support import WorkFixture

OUT = Path(".local/qa/functional-continuation/private-unclassified-work-browser")
DRAFT = "جواب بشري اصطناعي قبل التصنيف.\nسطر ثانٍ <script> محفوظ كنص، بلا تنفيذ."


@override_settings(**{**FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class PrivateUnclassifiedWorkBrowserTests(WorkFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, call):
        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '15s'")
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def submit(self, page, button, *, expected=200):
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, expected, page.locator("body").inner_text()[:500])

    def capture(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    @staticmethod
    def original_snapshot():
        return {
            "sources": list(CaseSource.objects.order_by("pk").values()),
            "evidence": list(CaseEvidence.objects.order_by("pk").values()),
        }

    @staticmethod
    def state():
        return {
            "case": Case.objects.values("approved_answer_id", "stage").get(),
            "answers": list(AnswerRevision.objects.values("id", "text", "text_sha256")),
            "decisions": list(
                CaseDecision.objects.values("answer_id", "action", "subject_id", "provider_id")
            ),
            "classifications": ClassificationRevision.objects.count(),
        }

    @staticmethod
    def workspace_button(page):
        return page.locator(
            '.mufti-case-nav form:has(input[name="action"][value="case_workspace"]) button'
        )

    def test_native_draft_approval_without_classification_and_current_work_revocation(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected native work proof requires FATWA_BROWSER_SANDBOX=1")
        self.assertIn("apps.data_privacy.integration.PrivacyResponses", settings.MIDDLEWARE)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        before = self.original_snapshot()
        question = before["sources"][0]["original_question"]
        self.assertEqual(ClassificationRevision.objects.count(), 0)
        # This fixture is the entire opt-in policy: actual MUFTI, this case and
        # this actor's new answers. It grants no other purpose or public access.
        self.permit_private_work()
        errors, external = [], []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )
            context = browser.new_context(viewport={"width": 320, "height": 900})

            def route(request):
                url = urlsplit(request.request.url)
                if url.scheme != "http" or url.netloc != urlsplit(self.live_server_url).netloc:
                    external.append(request.request.url)
                    request.abort()
                else:
                    request.continue_()

            context.route("**/*", route)
            context.tracing.start(screenshots=True, snapshots=True)
            try:
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                staff_url = self.live_server_url + "/casework/staff/"
                self.assertEqual(page.goto(staff_url + "login/").status, 200)
                page.locator('[name="credential"]').fill(CREDENTIALS["mufti"])
                self.submit(page, page.locator('form:has(input[name="credential"]) button'))
                self.submit(
                    page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True)
                )
                # Enter the connected workspace through its existing native tab.
                with page.expect_request(
                    lambda request: request.url == staff_url and request.method == "POST"
                ) as opening:
                    self.submit(page, self.workspace_button(page))
                self.assertEqual(parse_qs(opening.value.post_data)["action"], ["case_workspace"])
                self.assertEqual(
                    page.locator("#mufti-evidence-1 .original").text_content(), question
                )
                self.capture(page, "pending-classification-workspace")
                page.locator("#answer-text").fill(DRAFT)
                with page.expect_request(
                    lambda request: request.url == staff_url and request.method == "POST"
                ) as saving:
                    self.submit(
                        page, page.get_by_role("button", name="حفظ مسودة الجواب", exact=True)
                    )
                sent = parse_qs(saving.value.post_data, keep_blank_values=True)
                self.assertEqual(sent["action"], ["draft"])
                # Native URL-encoded forms normalize textarea LF to CRLF. The
                # persisted source must match the real request, byte for byte.
                submitted = sent["text"][0].encode("utf-8")
                self.assertIn(b"\r\n", submitted)
                drafted = self.sync(self.state)
                self.assertEqual(len(drafted["answers"]), 1)
                answer = drafted["answers"][0]
                self.assertEqual(answer["text"].encode("utf-8"), submitted)
                self.assertEqual(answer["text_sha256"], hashlib.sha256(submitted).hexdigest())
                self.assertEqual(drafted["classifications"], 0)
                self.assertEqual(drafted["decisions"], [])
                self.assertIn("<script>", page.locator("#review-answer").inner_text())
                page.locator("#approval-note").fill("قرار بشري اصطناعي مستقل")
                self.submit(page, page.get_by_role("button", name="اعتماد هذه النسخة", exact=True))
                self.assertIn(
                    "الاعتماد المسجل مطابق للوقائع الحالية",
                    page.locator("#mufti-approval-state").inner_text(),
                )
                approved = self.sync(self.state)
                self.assertEqual(approved["case"]["approved_answer_id"], answer["id"])
                self.assertEqual(approved["case"]["stage"], "ANSWERED")
                self.assertEqual(
                    approved["decisions"],
                    [
                        {
                            "answer_id": answer["id"],
                            "action": "APPROVE",
                            "subject_id": "mufti",
                            "provider_id": self.directory.provider_id,
                        }
                    ],
                )
                self.assertEqual(approved["classifications"], 0)
                self.assertEqual(self.sync(self.original_snapshot), before)
                self.capture(page, "human-answer-approved")

                # Reuse the form already rendered with the successful answer.
                # The URL/form is not a retained grant once current policy ends.
                self.authority.work.clear()
                self.authority.creators.clear()
                self.submit(page, self.workspace_button(page), expected=404)
                for private in (
                    question,
                    DRAFT.splitlines()[0],
                    self.receipt["public_ref"],
                    str(answer["id"]),
                ):
                    self.assertNotIn(private, page.content())
                self.capture(page, "current-work-revoked")
                self.assertEqual(self.sync(self.state), approved)
                self.assertEqual(self.sync(self.original_snapshot), before)

                self.permit_private_work()
                self.assertEqual(page.goto(staff_url).status, 200)
                self.submit(
                    page, page.get_by_role("button", name=self.receipt["public_ref"], exact=True)
                )
                self.assertIn(
                    "الاعتماد المسجل مطابق للوقائع الحالية",
                    page.locator("#mufti-approval-state").inner_text(),
                )
                self.assertEqual(self.sync(self.state), approved)
                self.assertEqual(self.sync(self.original_snapshot), before)
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "actual_role": "MUFTI",
                            "native_workspace_action": "case_workspace",
                            "native_draft_approved": True,
                            "classification_rows": 0,
                            "question_bytes_unchanged": True,
                            "submitted_answer_bytes_preserved": True,
                            "post_render_work_revocation_denied": True,
                            "positive_read_after_denial": True,
                            "keyboard_submit": True,
                            "external_requests": external,
                            "page_errors": errors,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                context.tracing.stop(path=str(OUT / "trace.zip"))
                context.close()
                browser.close()
