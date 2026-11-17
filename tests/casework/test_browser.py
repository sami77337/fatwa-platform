"""Real Chrome: two isolated website cases, human decisions and capability recovery."""

import json
import os
import re
import secrets
import shutil
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.casework.models import AnswerRevision, Case, CaseDecision, CaseEvidence, CaseSource
from apps.delivery_queue.models import ApprovalClaim, DeliveryAttempt, DeliveryIntent
from tests.casework.test_http import WEB_SETTINGS, Directory

BASE = "/casework/"
STATUS = BASE + "status/"
STAFF = BASE + "staff/"
LOGIN = STAFF + "login/"
OUT = Path(".local/qa/v6-casework/browser")
ALPHA = "  سُؤال ألف الاصطناعي <نص محفوظ>؟  "
BETA = "  سُؤال باء المستقل — بلفظه الأصلي.  "
CLARIFICATION = "وضّح الواقعة في هذا المثال الاصطناعي."
FOLLOWUP = "تعقيب ألف الاصطناعي الذي يغيّر الوقائع."
FIRST_DRAFT = "مسودة بشرية أولى قبل وصول التوضيح."
FINAL_DRAFT = "مسودة بشرية جديدة مبنية على التوضيح الاصطناعي."
BETA_DRAFT = "مسودة بشرية مستقلة لقضية باء الاصطناعية."


@override_settings(**WEB_SETTINGS)
class CaseworkBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        self.directory = Directory()
        self.directory.credential = secrets.token_hex(32)

        def recovery(subject_id, public_ref):
            if subject_id != self.directory.current.subject_id:
                raise ValueError("untrusted_recovery_subject")
            if public_ref not in self.directory.current.case_keys:
                raise ValueError("untrusted_recovery_scope")
            return Case.objects.get(public_ref=public_ref).requester_id

        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_CASEWORK_RECOVERY_RESOLVER=recovery,
            SECURE_REFERRER_POLICY="same-origin",
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def sync(self, function):
        """Keep ORM work off Playwright's synchronous event-loop thread."""

        def call():
            close_old_connections()
            try:
                return function()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=20)

    def submit(self, page, button, *, code=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            button.click()
        response = navigation.value
        self.assertIsNotNone(response, "native form did not navigate")
        self.assertEqual(response.status, code)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        return response

    def status(self, page, token, *, code=200):
        response = page.goto(self.live_server_url + STATUS)
        self.assertEqual(response.status, 200)
        page.locator("#tracking-token").fill(token)
        return self.submit(page, page.get_by_role("button", name="استعلام عن الحالة"), code=code)

    def no_requester_leaks(self, page, own_ref, other_ref, private_ids, tokens):
        document = unescape(page.content())
        self.assertTrue(own_ref in document, "own public reference missing")
        forbidden = [
            other_ref,
            *private_ids,
            *tokens,
            ALPHA,
            BETA,
            FIRST_DRAFT,
            FINAL_DRAFT,
            BETA_DRAFT,
            "RECEIVED",
            "UNDER_REVIEW",
            "NEEDS_CLARIFICATION",
            "ANSWERED",
            "RETURNED_FOR_CHANGES",
        ]
        self.assertTrue(
            all(value not in document for value in forbidden),
            "requester response exposed private content, token or internal state",
        )
        self.assertEqual(page.locator("#tracking-token").input_value(), "")
        self.assertEqual(page.locator("#followup-token").input_value(), "")

    def capture(self, page, name, role, width, height, evidence):
        page.set_viewport_size({"width": width, "height": height})
        self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
        # Issuance and recovery screens contain one-time secrets and are never captured.
        self.assertEqual(page.locator("#issued-token, #replacement-token").count(), 0)
        self.assertTrue(
            all(
                not value
                for value in page.locator("input[type=password]").evaluate_all(
                    "elements => elements.map(element => element.value)"
                )
            ),
            "password values must be empty before screenshot",
        )
        page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)
        evidence["views"].append(
            {"role": role, "width": width, "height": height, "rtl": True, "no_overflow": True}
        )

    def test_two_case_browser_journey_and_revoked_capabilities(self):
        from playwright.sync_api import sync_playwright

        chrome = os.environ.get("FATWA_FASTBUILD_BROWSER") or shutil.which("google-chrome")
        self.assertTrue(chrome and Path(chrome).is_file(), "real Chrome executable required")
        OUT.mkdir(parents=True, exist_ok=True)
        evidence = {
            "status": "ERROR",
            "views": [],
            "external_requests": 0,
            "unsafe_url_requests": 0,
            "page_errors": 0,
            "tests_run": 1,
            "deployment": "NOT_DEPLOYED",
            "sent": False,
        }
        origin = self.live_server_url
        netloc = urlsplit(origin).netloc
        allowed_paths = {
            BASE,
            STATUS,
            STAFF,
            LOGIN,
            BASE + "followup/",
            STAFF + "logout/",
            BASE + "casework.css",
            "/favicon.ico",
        }
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=chrome,
                    headless=True,
                    chromium_sandbox=True,
                    args=["--disable-dev-shm-usage"],
                )
                evidence["browser_version"] = browser.version
                try:

                    def context(width, height):
                        ctx = browser.new_context(viewport={"width": width, "height": height})
                        ctx.set_default_timeout(15000)

                        def route(request_route):
                            parsed = urlsplit(request_route.request.url)
                            if parsed.scheme != "http" or parsed.netloc != netloc:
                                evidence["external_requests"] += 1
                                request_route.abort()
                            elif parsed.query or parsed.path not in allowed_paths:
                                # Store counts only, never a URL which could contain a secret.
                                evidence["unsafe_url_requests"] += 1
                                request_route.abort()
                            else:
                                request_route.continue_()

                        ctx.route("**/*", route)
                        return ctx

                    alpha_ctx = context(320, 780)
                    beta_ctx = context(1280, 900)
                    staff_ctx = context(1280, 900)
                    alpha, beta, staff = (
                        ctx.new_page() for ctx in (alpha_ctx, beta_ctx, staff_ctx)
                    )

                    def page_error(_error):
                        evidence["page_errors"] += 1

                    for page in (alpha, beta, staff):
                        page.on("pageerror", page_error)

                    def intake(page, text):
                        self.assertEqual(page.goto(origin + BASE).status, 200)
                        page.locator("#question").fill(text)
                        self.submit(page, page.get_by_role("button", name="حفظ السؤال"))
                        ref = page.locator("#public-reference").inner_text()
                        token = page.locator("#issued-token").inner_text()
                        self.assertTrue(re.fullmatch(r"FT-[0-9]{4}-[A-F0-9]{20}", ref) is not None)
                        self.assertTrue(re.fullmatch(r"rt_[A-Za-z0-9_-]{43}", token) is not None)
                        self.assertFalse(bool(urlsplit(page.url).query), "intake added a URL query")
                        return ref, token

                    alpha_ref, alpha_token = intake(alpha, ALPHA)
                    beta_ref, beta_token = intake(beta, BETA)
                    self.assertTrue(alpha_ref != beta_ref, "two intakes reused a public reference")
                    self.assertTrue(alpha_token != beta_token, "two cases shared a capability")
                    identities = self.sync(
                        lambda: list(
                            Case.objects.order_by("created_at").values_list("id", "requester_id")
                        )
                    )
                    private_ids = [str(value) for row in identities for value in row]
                    tokens = [alpha_token, beta_token]
                    self.assertEqual(len(identities), 2)
                    self.assertEqual(alpha.goto(origin + STAFF).status, 403)
                    self.status(alpha, alpha_token)
                    self.no_requester_leaks(alpha, alpha_ref, beta_ref, private_ids, tokens)
                    self.assertIn("تم استلام السؤال", alpha.locator("#case-status").inner_text())
                    self.status(beta, beta_token)
                    self.no_requester_leaks(beta, beta_ref, alpha_ref, private_ids, tokens)

                    # Server-only fixture assignments are the sole source of staff scope.
                    self.directory.grant(alpha_ref, beta_ref)
                    self.assertEqual(staff.goto(origin + LOGIN).status, 200)
                    staff.locator("#credential").fill(self.directory.credential)
                    with staff.expect_response(
                        lambda response: (
                            response.url == origin + LOGIN and response.request.method == "POST"
                        )
                    ) as login:
                        self.submit(staff, staff.get_by_role("button", name="دخول المكتب"))
                    self.assertEqual(login.value.status, 303)

                    def open_case(ref, original):
                        self.submit(staff, staff.get_by_role("button", name=ref, exact=True))
                        self.assertEqual(
                            staff.locator("#original-question").text_content(), original
                        )

                    open_case(alpha_ref, ALPHA)
                    self.assertTrue(
                        BETA not in unescape(staff.content()),
                        "selected case exposed other question",
                    )
                    staff.locator("#answer-text").fill(FIRST_DRAFT)
                    self.submit(staff, staff.get_by_role("button", name="حفظ مسودة الجواب"))
                    staff.locator("#clarification-text").fill(CLARIFICATION)
                    self.submit(staff, staff.get_by_role("button", name="طلب استيضاح"))
                    self.status(alpha, alpha_token)
                    self.assertIn(CLARIFICATION, alpha.locator("#case-status").inner_text())
                    self.no_requester_leaks(alpha, alpha_ref, beta_ref, private_ids, tokens)
                    alpha.locator("#followup-token").fill(alpha_token)
                    alpha.locator("#followup-text").fill(FOLLOWUP)
                    self.submit(alpha, alpha.get_by_role("button", name="إضافة التعقيب"))
                    self.assertIn("قيد المراجعة", alpha.locator("#case-status").inner_text())
                    open_case(alpha_ref, ALPHA)
                    self.assertIn(FOLLOWUP, staff.locator("body").inner_text())
                    staff.locator("#answer-text").fill(FINAL_DRAFT)
                    self.submit(staff, staff.get_by_role("button", name="حفظ مسودة الجواب"))
                    # Only the latest evidence-bound answer is approved; old draft remains visible.
                    self.submit(staff, staff.get_by_role("button", name="اعتماد هذه النسخة").last)
                    self.assertIn(
                        "اعتماد بشري حالي لهذه النسخة", staff.locator("body").inner_text()
                    )
                    self.capture(staff, "staff-alpha", "staff", 1280, 900, evidence)
                    self.status(alpha, alpha_token)
                    self.assertIn(
                        "اكتملت مراجعة الجواب", alpha.locator("#case-status").inner_text()
                    )
                    self.no_requester_leaks(alpha, alpha_ref, beta_ref, private_ids, tokens)
                    self.capture(alpha, "requester-alpha", "requester", 320, 780, evidence)

                    # A second independent case completes a separate human answer and decision.
                    staff.set_viewport_size({"width": 320, "height": 780})
                    open_case(beta_ref, BETA)
                    self.assertTrue(
                        ALPHA not in unescape(staff.content()), "second case exposed first question"
                    )
                    staff.locator("#answer-text").fill(BETA_DRAFT)
                    self.submit(staff, staff.get_by_role("button", name="حفظ مسودة الجواب"))
                    self.submit(
                        staff, staff.get_by_role("button", name="اعتماد هذه النسخة", exact=True)
                    )
                    self.capture(staff, "staff-beta", "staff", 320, 780, evidence)
                    self.status(beta, beta_token)
                    self.assertIn("اكتملت مراجعة الجواب", beta.locator("#case-status").inner_text())
                    self.no_requester_leaks(beta, beta_ref, alpha_ref, private_ids, tokens)
                    self.capture(beta, "requester-beta", "requester", 1280, 900, evidence)

                    open_case(alpha_ref, ALPHA)
                    self.submit(staff, staff.get_by_role("button", name="استرداد رمز جديد"))
                    replacement = staff.locator("#replacement-token").inner_text()
                    self.assertTrue(
                        replacement not in tokens, "recovery reused a previous capability"
                    )
                    tokens.append(replacement)
                    self.status(alpha, alpha_token, code=404)
                    self.assertEqual(alpha.locator("#case-status").count(), 0)
                    self.status(alpha, replacement)
                    self.no_requester_leaks(alpha, alpha_ref, beta_ref, private_ids, tokens)
                    self.submit(staff, staff.get_by_role("button", name="إبطال رموز الوصول"))
                    self.status(alpha, replacement, code=404)
                    self.assertEqual(alpha.locator("#case-status").count(), 0)
                    self.status(beta, beta_token)
                    self.no_requester_leaks(beta, beta_ref, alpha_ref, private_ids, tokens)
                    self.assertIn("اكتملت مراجعة الجواب", beta.locator("#case-status").inner_text())

                    # Status reads may consume a rate-limit budget, but never alter case history.
                    def state():
                        return list(
                            Case.objects.order_by("created_at").values_list(
                                "stage",
                                "revision",
                                "evidence_version",
                                "answer_revision",
                                "approved_answer_id",
                            )
                        )

                    before = self.sync(state)
                    self.status(beta, beta_token)
                    self.assertEqual(self.sync(state), before)
                    final = self.sync(
                        lambda: {
                            "cases": Case.objects.count(),
                            "sources": CaseSource.objects.count(),
                            "evidence": CaseEvidence.objects.count(),
                            "answers": AnswerRevision.objects.count(),
                            "decisions": CaseDecision.objects.count(),
                            "claims": ApprovalClaim.objects.count(),
                            "delivery_intents": DeliveryIntent.objects.count(),
                            "delivery_attempts": DeliveryAttempt.objects.count(),
                            "originals_exact": sorted(
                                CaseSource.objects.values_list("original_question", flat=True)
                            )
                            == sorted([ALPHA, BETA]),
                        }
                    )
                    self.assertEqual(
                        final,
                        {
                            "cases": 2,
                            "sources": 2,
                            "evidence": 3,
                            "answers": 3,
                            "decisions": 2,
                            "claims": 0,
                            "delivery_intents": 0,
                            "delivery_attempts": 0,
                            "originals_exact": True,
                        },
                    )
                    self.assertEqual(evidence["external_requests"], 0)
                    self.assertEqual(evidence["unsafe_url_requests"], 0)
                    self.assertEqual(evidence["page_errors"], 0)
                    evidence.update(
                        status="PASS",
                        separate_requester_browsers=True,
                        trusted_staff_login=True,
                        two_human_approved_cases=True,
                        clarification_followup_bound=True,
                        prior_draft_preserved=True,
                        rotated_old_token_rejected=True,
                        replacement_accepted_then_revoked=True,
                        other_case_unaffected=True,
                        requester_no_content_leak=True,
                        status_read_did_not_mutate_cases=True,
                        final=final,
                    )
                    for ctx in (alpha_ctx, beta_ctx, staff_ctx):
                        ctx.close()
                finally:
                    browser.close()
        finally:
            (OUT / "evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
