"""One synthetic browser journey across canonical V7 cases, sources and publication."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from apps.case_attachments.models import CaseAttachment
from apps.case_citations.models import AnswerCitation
from apps.casework.models import AnswerRevision, Case
from apps.experimental_publication.authority import PublicationAuthority
from apps.experimental_publication.models import PublicationAction, PublicationEdition
from apps.reference.ingest import ingest_catalog
from tests.casework.delivery_fixtures import CaseDeliveryFixture
from tests.casework.test_core import TestDirectory
from tests.casework.test_http import WEB_SETTINGS
from tests.reference.test_catalog import fixture

QUESTION = "سؤال اصطناعي خاص لا يظهر في المكتبة المغلقة."
FOLLOWUP = "تفصيل اصطناعي جديد من السائل بعد طلب المفتي."
ANSWER = "جواب بشري اصطناعي للتجربة المتصلة فقط، مع إحالة مفهرسة."
PUBLIC_BODY = "نسخة تحريرية اصطناعية من الجواب للتجربة المغلقة فقط."
FILE_BYTES = "مرفق اصطناعي أصلي محفوظ حرفيًا.\n".encode()
OUT = Path(".local/qa/v7/browser")


class BrowserDirectory(TestDirectory):
    """Two explicitly scoped test principals; production has no such provider."""

    def resolve(self, subject_id):
        base = super().resolve("synthetic-mufti")
        return (
            replace(base, subject_id=subject_id)
            if subject_id in {"synthetic-mufti", "synthetic-publisher"}
            else None
        )

    def authenticate(self, credential):
        subjects = {"M" * 64: "synthetic-mufti", "P" * 64: "synthetic-publisher"}
        return self.resolve(subjects[credential]) if credential in subjects else None


class BrowserPublicationAuthority(PublicationAuthority):
    def __init__(self, directory):
        self.directory = directory

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == self.directory.provider_id
            and subject_id == "synthetic-publisher"
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and action in {"APPROVE", "WITHDRAW"}
        )


@override_settings(
    **{
        **WEB_SETTINGS,
        "ROOT_URLCONF": "config.campaign_urls",
        "FATWA_CASE_ATTACHMENTS_ENABLED": True,
        "FATWA_CASE_CITATIONS_ENABLED": True,
        "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED": True,
        "FATWA_CASEWORK_PRIVATE_ANSWER_ENABLED": True,
    }
)
class V7ConnectedBrowserTests(LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, callback):
        def call():
            close_old_connections()
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(call).result(timeout=30)

    def click(self, page, name, code=200):
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            page.get_by_role("button", name=name, exact=True).click()
        self.assertEqual(navigation.value.status, code)
        self.assertIn("no-store", navigation.value.headers.get("cache-control", ""))

    def capture(self, page, name):
        # DOMContentLoaded alone does not guarantee the external CSS is loaded.
        # Measure the rendered contract, without retries or a larger timeout.
        initial = page.evaluate("""() => ({ready: document.readyState,
            width: innerWidth, actual: document.documentElement.scrollWidth,
            css: [...document.styleSheets].some(s => s.href &&
                new URL(s.href).pathname === '/casework/casework.css' && s.cssRules.length > 0)
        })""")
        print("V7_LAYOUT_INITIAL=" + json.dumps({"capture": name, **initial}, sort_keys=True))
        page.wait_for_function("""() => [...document.styleSheets].some(sheet =>
            sheet.href && new URL(sheet.href).pathname === '/casework/casework.css'
            && sheet.cssRules.length > 0)""")
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            actual = page.evaluate("document.documentElement.scrollWidth")
            if actual > width:
                diagnostics = page.evaluate("""() => ({
                    ready: document.readyState,
                    styles: [...document.styleSheets].map(s => ({
                        href: new URL(s.href || location.href).pathname,
                        rules: s.cssRules.length
                    })),
                    overflow: [...document.querySelectorAll('body *')].filter(e => {
                        const r = e.getBoundingClientRect();
                        return r.right > innerWidth || r.left < 0;
                    }).slice(0, 30).map(e => ({
                        tag: e.tagName, id: e.id, width: e.getBoundingClientRect().width,
                        wrap: getComputedStyle(e).overflowWrap,
                        whitespace: getComputedStyle(e).whiteSpace
                    }))
                })""")
                print(
                    "V7_LAYOUT_FAILURE="
                    + json.dumps(
                        {"capture": name, "width": width, "actual": actual, **diagnostics},
                        sort_keys=True,
                    )
                )
            self.assertLessEqual(actual, width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def test_question_attachment_cited_approval_private_answer_and_independent_publication(self):
        from playwright.sync_api import sync_playwright

        spec, rows = fixture()
        spec = replace(spec, source_book_id="622")
        preview = ingest_catalog(spec, rows)
        edition = ingest_catalog(
            spec, rows, dry_run=False, expected_checksum=preview.checksum
        ).edition_id
        directory = BrowserDirectory()
        OUT.mkdir(parents=True, exist_ok=True)
        external, errors = [], []
        with (
            override_settings(
                FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
                FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY=BrowserPublicationAuthority(directory),
            ),
            sync_playwright() as playwright,
        ):
            sandbox = os.environ.get("FATWA_BROWSER_SANDBOX", "1") != "0"
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=sandbox,
                args=["--disable-dev-shm-usage"],
            )
            try:
                contexts = [
                    browser.new_context(viewport={"width": 1280, "height": 900}) for _ in range(4)
                ]
                for context in contexts:

                    def route(request_route):
                        if (
                            urlsplit(request_route.request.url).netloc
                            != urlsplit(self.live_server_url).netloc
                        ):
                            external.append("external_request")
                            request_route.abort()
                        else:
                            request_route.continue_()

                    context.route("**/*", route)
                requester, staff, foreign, publisher = [c.new_page() for c in contexts]
                for page in (requester, staff, foreign, publisher):
                    page.on("pageerror", lambda error: errors.append(str(error)))

                def intake(page, question):
                    self.assertEqual(page.goto(self.live_server_url + "/casework/").status, 200)
                    page.locator("#question").fill(question)
                    self.click(page, "حفظ السؤال")
                    ref = page.locator("#public-reference").inner_text()
                    token = page.locator("#issued-token").inner_text()
                    page.get_by_role("link", name="متابعة هذا السؤال", exact=True).click()
                    return ref, token

                public_ref, token = intake(requester, QUESTION)
                foreign_ref, foreign_token = intake(foreign, "سؤال سائل اصطناعي آخر مستقل.")
                directory.refs = frozenset({public_ref})
                self.click(requester, "مرفقات سؤالي")
                requester.locator('input[name="attachment"]').set_input_files(
                    {
                        "name": "synthetic-evidence.txt",
                        "mimeType": "text/plain",
                        "buffer": FILE_BYTES,
                    }
                )
                requester.locator('input[name="synthetic_only"]').check()
                self.click(requester, "حفظ الأصل وإضافة الوقائع")
                self.assertIn("synthetic-evidence.txt", requester.content())
                self.click(requester, "معاينة synthetic-evidence.txt")
                self.assertIn(FILE_BYTES.decode().strip(), requester.locator("pre").inner_text())
                attachment_id = requester.locator('input[name="attachment_id"]').first.input_value()
                self.capture(requester, "requester-attachment")

                # Browser-originated forged foreign download, using that requester's own CSRF.
                self.click(foreign, "مرفقات سؤالي")
                with foreign.expect_navigation(wait_until="domcontentloaded") as rejected:
                    foreign.evaluate(
                        """id => {
                        const form = document.createElement('form'); form.method='POST';
                        form.action='/casework/status/';
                        const fields = {action:'attachment_download', attachment_id:id,
                          csrfmiddlewaretoken:document.querySelector('[name=csrfmiddlewaretoken]').value};
                        for (const [name,value] of Object.entries(fields)) {
                            const input=document.createElement('input'); input.type='hidden';
                            input.name=name; input.value=value; form.appendChild(input);
                        } document.body.appendChild(form); form.submit();
                    }""",
                        attachment_id,
                    )
                self.assertEqual(rejected.value.status, 409)
                self.assertNotIn(FILE_BYTES.decode().strip(), foreign.content())
                self.assertNotIn(public_ref, foreign.content())

                def login(page, credential):
                    page.goto(self.live_server_url + "/casework/staff/login/")
                    page.locator("#credential").fill(credential)
                    self.click(page, "دخول المكتب")
                    self.click(page, public_ref)

                login(staff, "M" * 64)
                self.click(staff, "مرفقات القضية")
                self.click(staff, "معاينة synthetic-evidence.txt")
                self.assertIn(FILE_BYTES.decode().strip(), staff.locator("pre").inner_text())
                with staff.expect_download() as download:
                    staff.get_by_role(
                        "button", name="تنزيل الأصل synthetic-evidence.txt", exact=True
                    ).click()
                self.assertEqual(Path(download.value.path()).read_bytes(), FILE_BYTES)
                self.capture(staff, "mufti-attachment")
                self.click(staff, "العودة إلى القضية")
                staff.locator("#clarification-text").fill("وضح التفصيل الاصطناعي اللازم.")
                self.click(staff, "طلب استيضاح")
                requester.goto(self.live_server_url + "/casework/status/")
                self.assertIn(
                    "وضح التفصيل", requester.locator("#requested-clarification").inner_text()
                )
                requester.locator("#workspace-followup").fill(FOLLOWUP)
                self.click(requester, "حفظ التعقيب")
                self.click(staff, public_ref)
                self.assertIn(FOLLOWUP, staff.content())

                self.click(staff, "تحرير جواب بإحالة موثقة")
                staff.locator("#answer").fill(ANSWER)
                staff.locator("#edition").select_option(str(edition))
                staff.locator("#query").fill("فرع")
                self.click(staff, "البحث مع الاحتفاظ بالمسودة")
                self.assertEqual(staff.locator("#answer").input_value(), ANSWER)
                staff.locator("#note").fill("تعليق تحريري اصطناعي مستقل عن عنوان المصدر.")
                self.click(staff, "إضافة الموضع 2 إلى القائمة")
                staff.locator('input[name="confirm"]').check()
                self.click(staff, "حفظ الجواب والقائمة الكاملة")
                self.capture(staff, "cited-answer")
                self.click(staff, "العودة إلى القضية دون حفظ هذه المسودة")
                self.click(staff, "اعتماد هذه النسخة")
                requester.goto(self.live_server_url + "/casework/status/")
                self.assertNotIn(ANSWER, requester.content())
                self.assertNotIn("تعليق تحريري اصطناعي", requester.content())

                case_id = self.sync(lambda: str(Case.objects.get(public_ref=public_ref).pk))
                receipt = {"case_id": case_id, "public_ref": public_ref, "token": token}
                # Test-only external signature fixtures bind to the browser's SAME case/answer.
                delivery = CaseDeliveryFixture()
                delivery.intake = lambda suffix: receipt
                delivery.setUp()
                delivery.directory = directory
                self.sync(delivery.stage)
                self.sync(delivery.deliver)
                with override_settings(
                    FATWA_CASE_DELIVERY_PROVIDER_VERIFIER=delivery.channel_verifier
                ):
                    requester.goto(self.live_server_url + "/casework/status/")
                    self.assertIn(ANSWER, requester.content())
                    self.assertNotIn("تعليق تحريري اصطناعي", requester.content())
                    self.assertNotIn(foreign_ref, requester.content())
                    self.assertNotIn(token, requester.content())
                    self.capture(requester, "private-approved-answer")

                self.click(staff, "نسخة النشر التجريبية")
                staff.locator("#publication-title").fill("عنوان نشر اصطناعي متصل")
                staff.locator("#publication-category").fill("تصنيف تجربة")
                staff.locator("#publication-body").fill(PUBLIC_BODY)
                self.click(staff, "حفظ نسخة مرشحة جديدة")
                review_form = staff.locator('form:has(input[value="pub_review"])')
                review_form.locator('input[name="confirm"]').check()
                self.click(staff, "تسجيل مراجعة التحرير والخصوصية")
                self.click(staff, "المكتبة التجريبية المغلقة")
                self.assertIn("لا توجد نتائج متاحة", staff.content())
                self.assertNotIn(PUBLIC_BODY, staff.content())

                login(publisher, "P" * 64)
                self.click(publisher, "نسخة النشر التجريبية")
                approve_form = publisher.locator('form:has(input[value="pub_approve"])')
                approve_form.locator('input[name="confirm"]').check()
                self.click(publisher, "موافقة نشر مستقلة")
                self.click(publisher, "المكتبة التجريبية المغلقة")
                publisher.locator("#publication-query").fill("عنوان نشر")
                self.click(publisher, "بحث")
                self.assertIn(PUBLIC_BODY, publisher.content())
                self.assertIn("فَرْعٌ تَجْرِيبِيّ", publisher.content())
                for hidden in (
                    QUESTION,
                    FOLLOWUP,
                    FILE_BYTES.decode().strip(),
                    public_ref,
                    token,
                    foreign_token,
                    "تعليق تحريري اصطناعي",
                ):
                    self.assertNotIn(hidden, publisher.content())
                self.capture(publisher, "experimental-library")
                publication_id = publisher.locator('input[name="edition_id"]').input_value()
                self.click(publisher, "فتح صفحة النسخة")
                self.assertEqual(publisher.title(), "عنوان نشر اصطناعي متصل | المكتبة التجريبية")
                self.assertIn(PUBLIC_BODY, publisher.locator("article").inner_text())
                publisher.locator("article details summary").click()
                self.assertIn("فَرْعٌ تَجْرِيبِيّ", publisher.locator("article").inner_text())
                self.assertIn("طبعة اختبار", publisher.locator("article").inner_text())
                self.assertNotIn(QUESTION, publisher.content())
                self.assertNotIn(public_ref, publisher.content())
                self.capture(publisher, "published-page")
                self.click(publisher, "العودة إلى المكتبة التجريبية")
                self.click(publisher, "العودة إلى القضايا")
                self.click(publisher, public_ref)
                self.click(publisher, "نسخة النشر التجريبية")
                publisher.locator(
                    'form:has(input[value="pub_withdraw"]) input[name="confirm"]'
                ).check()
                self.click(publisher, "سحب النسخة")
                self.click(publisher, "المكتبة التجريبية المغلقة")
                self.assertNotIn(PUBLIC_BODY, publisher.content())
                self.assertIn("لا توجد نتائج متاحة", publisher.content())
                # A remembered publication ID cannot reopen the withdrawn page.
                with publisher.expect_navigation(wait_until="domcontentloaded") as withdrawn:
                    publisher.evaluate(
                        """id => {
                        const form=document.createElement('form'); form.method='POST';
                        form.action='/casework/staff/';
                        const fields={action:'pub_read',edition_id:id,
                          csrfmiddlewaretoken:document.querySelector('[name=csrfmiddlewaretoken]').value};
                        for (const [name,value] of Object.entries(fields)) {
                            const input=document.createElement('input'); input.type='hidden';
                            input.name=name; input.value=value; form.appendChild(input);
                        } document.body.appendChild(form); form.submit();
                    }""",
                        publication_id,
                    )
                self.assertEqual(withdrawn.value.status, 404)
                self.assertNotIn(PUBLIC_BODY, publisher.content())
                self.assertNotIn("عنوان نشر اصطناعي متصل", publisher.content())

                def canonical_links():
                    case = Case.objects.get(pk=case_id)
                    attachment = CaseAttachment.objects.get(case=case)
                    citation = AnswerCitation.objects.get(answer=case.approved_answer)
                    publication = PublicationEdition.objects.get(case=case)
                    return {
                        "case_count": Case.objects.count(),
                        "answer_count": AnswerRevision.objects.filter(case=case).count(),
                        "evidence_version": case.evidence_version,
                        "attachment_version": attachment.evidence.version,
                        "original_preserved": bytes(attachment.original) == FILE_BYTES,
                        "same_answer": publication.answer_id
                        == citation.answer_id
                        == case.approved_answer_id,
                        "publication_actions": list(
                            PublicationAction.objects.filter(edition=publication)
                            .order_by("created_at")
                            .values_list("action", flat=True)
                        ),
                    }

                evidence = self.sync(canonical_links)
                self.assertEqual(
                    evidence,
                    {
                        "case_count": 2,
                        "answer_count": 1,
                        "evidence_version": 3,
                        "attachment_version": 2,
                        "original_preserved": True,
                        "same_answer": True,
                        "publication_actions": ["REVIEW", "APPROVE", "WITHDRAW"],
                    },
                )
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "browser": browser.version,
                            "sandbox": sandbox,
                            "widths": [320, 1280],
                            "external_requests": 0,
                            "page_errors": 0,
                            "foreign_download_status": 409,
                            "withdrawn_page_status": 404,
                            "published_detail": "PASS",
                            "canonical": evidence,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                print(
                    f"V7 connected browser PASS: Chromium {browser.version}, sandbox={sandbox}, "
                    "320/1280, real upload/download, foreign denied, exact cited answer, "
                    "signed private delivery fixture, independent publication and withdrawal."
                )
            finally:
                browser.close()
