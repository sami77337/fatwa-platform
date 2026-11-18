"""Native loopback forms and original-document request; no claim of PDF plugin rendering."""

import os

from django.test import LiveServerTestCase, override_settings

from .models import PdfCitation
from .tests import SETTINGS, Fixture


@override_settings(**SETTINGS)
class PdfBrowserTests(Fixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_native_page_review_confirmation_and_withdrawal(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
            )
            try:
                context = browser.new_context(viewport={"width": 360, "height": 900})
                page = context.new_page()
                external, errors = [], []
                page.on(
                    "request",
                    lambda r: (
                        external.append(r.url)
                        if r.url.startswith(("http://", "https://", "ws://", "wss://"))
                        and not r.url.startswith(self.live_server_url + "/")
                        else None
                    ),
                )
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(self.live_server_url + "/casework/staff/login/")
                page.locator('[name="credential"]').fill(
                    "synthetic-editor-credential-32-characters"
                )
                page.get_by_role("button", name="دخول المكتب", exact=True).click()
                with page.expect_navigation():
                    page.evaluate(
                        """fields => {
                        const f=document.createElement('form');f.method='POST';f.action='/casework/staff/';
                        fields.csrfmiddlewaretoken=document.querySelector('[name=csrfmiddlewaretoken]').value;
                        for(const [k,v] of Object.entries(fields)){const i=document.createElement('input');i.name=k;i.value=v;f.appendChild(i);}
                        document.body.appendChild(f);f.submit();
                    }""",
                        {"action": "pdf_desk", "case_ref": self.receipt["public_ref"]},
                    )
                page.locator('[name="page_number"]').fill("2")
                page.locator('[name="reason"]').fill("Synthetic physical page, no printed mapping")
                page.get_by_role("button", name="حفظ اقتراح بشري", exact=True).click()
                with page.expect_response(lambda r: "/review-document/" in r.url) as original:
                    page.get_by_role(
                        "button", name="معاينة خاصة للمراجعة قبل التأكيد", exact=True
                    ).click()
                self.assertEqual(original.value.status, 200)
                wire = context.request.get(original.value.url)
                self.assertIn("sandbox", wire.headers["content-security-policy"])
                self.assertEqual(wire.body(), self.pdf["raw"])
                print(
                    f"PDF_NAVIGATION_CSP={original.value.headers.get('content-security-policy')}; PDF_WIRE_CSP={wire.headers.get('content-security-policy')}"
                )
                self.assertIn(
                    "review-document/#page=2", page.locator("iframe").get_attribute("src")
                )
                confirm = page.get_by_role(
                    "button", name="تأكيد الموضع بعد المعاينة البشرية", exact=True
                )
                with page.expect_navigation(timeout=6000):
                    confirm.focus()
                    confirm.press("Enter")
                page.get_by_role("button", name="فتح الموضع المصرح به", exact=True).click()
                document_url = page.locator("iframe").get_attribute("src").split("#")[0]
                response = context.request.get(self.live_server_url + document_url)
                self.assertEqual(response.body(), self.pdf["raw"])
                self.assertIn("no-store", response.headers["cache-control"])
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                page.keyboard.press("Tab")
                self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                page.get_by_role("button", name="سحب الإحالة", exact=True).click()
                self.assertEqual(
                    context.request.get(self.live_server_url + document_url).status, 404
                )
                self.assertIn("WITHDRAWN", page.content())
                self.assertEqual(external, [])
                self.assertEqual(errors, [])
                print(
                    f"PDF_BROWSER={browser.version}; sandbox={os.environ.get('FATWA_TEST_BROWSER_NO_SANDBOX') != '1'}; physical page=2/3; withdrawal=404; plugin-rendering=NOT_ASSERTED"
                )
            finally:
                browser.close()
        row = PdfCitation.objects.get()
        self.assertEqual((row.page_number, row.page_count, row.printed_label), (2, 3, ""))
