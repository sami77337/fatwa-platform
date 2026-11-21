"""Protected native reference saves, public shares, actual printing and text copies."""

import json
import os
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from django.test import LiveServerTestCase, override_settings

from apps.public_answer_media.test_support import CREDENTIALS

from . import services
from .test_support import FEATURES, ReaderFixture

OUT = Path(".local/qa/functional-continuation/reader-tools-browser")
KEY = "fatwa.public.reader.references.v1"


@override_settings(**FEATURES)
class ReaderToolsBrowserTests(ReaderFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def capture(self, page, label, proof):
        for width, height in ((320, 780), (1280, 900)):
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            name = f"{label}-{width}.png"
            page.screenshot(path=str(OUT / name), full_page=True)
            proof["screenshots"].append(name)

    def submit(self, page, button):
        button.focus()
        with page.expect_navigation(wait_until="domcontentloaded") as event:
            button.press("Enter")
        self.assertEqual(event.value.status, 200)

    def click_link(self, page, label):
        with page.expect_navigation(wait_until="domcontentloaded") as event:
            page.get_by_role("link", name=label, exact=True).click()
        self.assertEqual(event.value.status, 200)
        return event.value

    def test_native_local_reference_share_print_download_and_current_withdrawal(self):
        from playwright.sync_api import expect, sync_playwright

        with services.reader_projection(self.publication.pk, action="DOWNLOAD_TEXT") as row:
            expected_copy = services.text_copy(row)
        OUT.mkdir(parents=True, exist_ok=True)
        proof = {
            "status": "ERROR",
            "sandbox": True,
            "widths": [320, 1280],
            "screenshots": [],
            "trace": "trace.zip",
            "traces": [],
            "external_requests": [],
            "page_errors": [],
            "observed_statuses": {},
            "stored_reference_keys": [],
            "printed_pdf": "approved-public-text.pdf",
        }
        contexts = []
        origin = self.live_server_url
        tools_url = f"/library-preview/reading/{self.publication.pk}/"
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

                    def new_page(name):
                        context = browser.new_context(
                            viewport={"width": 320, "height": 780},
                            color_scheme="dark",
                            accept_downloads=True,
                        )
                        context.route("**/*", local_only)
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                        contexts.append((name, context))
                        page = context.new_page()
                        page.on(
                            "pageerror",
                            lambda error: proof["page_errors"].append(type(error).__name__),
                        )
                        return page

                    page, other_device, publisher = [
                        new_page(name) for name in ("public", "other-device", "publisher")
                    ]
                    response = page.goto(
                        origin + f"/library-preview/editions/{self.publication.pk}/"
                    )
                    self.assertEqual(response.status, 200)
                    self.click_link(page, "حفظ ومشاركة وطباعة الجواب")
                    self.assertEqual(urlsplit(page.url).path, tools_url)
                    self.assertIsNone(page.evaluate("key => localStorage.getItem(key)", KEY))
                    self.assertNotIn("PRIVATE", page.locator("main").inner_text())
                    self.capture(page, "reader-tools", proof)

                    with page.expect_response(
                        lambda r: r.url.endswith("/save-reference/")
                    ) as event:
                        page.get_by_role(
                            "button", name="حفظ المرجع على هذا الجهاز", exact=True
                        ).click()
                    self.assertEqual(event.value.status, 200)
                    expect(page.locator("#reader-tool-status")).to_contain_text("حُفظ المرجع")
                    saved = json.loads(page.evaluate("key => localStorage.getItem(key)", KEY))
                    self.assertEqual(
                        saved,
                        [
                            {
                                "publication_id": str(self.publication.pk),
                                "content_sha256": self.publication.content_sha256,
                                "version": 1,
                            }
                        ],
                    )
                    proof["stored_reference_keys"] = sorted(saved[0])
                    self.click_link(page, "المراجع المحفوظة على هذا الجهاز")
                    expect(page.locator("#saved-references a")).to_have_text(self.publication.title)
                    self.capture(page, "saved-reference", proof)
                    self.click_link(page, self.publication.title)
                    response = other_device.goto(origin + "/library-preview/reading/saved/")
                    self.assertEqual(response.status, 200)
                    expect(other_device.locator("#reader-tool-status")).to_contain_text(
                        "لم تحفظ مراجع"
                    )
                    self.assertIsNone(
                        other_device.evaluate("key => localStorage.getItem(key)", KEY)
                    )
                    proof["separate_device_has_no_bookmarks"] = True

                    with page.expect_response(lambda r: r.url.endswith("/share-link/")) as event:
                        page.get_by_role(
                            "button", name="نسخ رابط النسخة العامة", exact=True
                        ).click()
                    self.assertEqual(event.value.status, 200)
                    expect(page.locator("#share-output")).to_be_visible()
                    expect(page.locator("#share-url")).to_have_value(
                        origin + f"/library-preview/editions/{self.publication.pk}/"
                    )
                    proof["shared_public_url"] = page.locator("#share-url").input_value()
                    self.assertNotIn(self.receipt["public_ref"], proof["shared_public_url"])

                    with page.expect_download() as download_event:
                        page.get_by_role(
                            "link", name="تنزيل نسخة النص المسموح بها", exact=True
                        ).click()
                    download = download_event.value
                    self.assertEqual(
                        download.suggested_filename, f"answer-{self.publication.pk}-v1.txt"
                    )
                    copied = Path(download.path()).read_bytes()
                    self.assertEqual(copied, expected_copy)
                    self.assertNotIn(b"PRIVATE", copied)
                    proof["download_sha256"] = sha256(copied).hexdigest()
                    proof["download_bytes"] = len(copied)

                    self.click_link(page, "فتح نسخة الطباعة المسموح بها")
                    self.assertEqual(
                        page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor"),
                        "rgb(255, 255, 255)",
                    )
                    self.capture(page, "print-light-in-dark-preference", proof)
                    # Observe the real native print event; do not replace window.print,
                    # browser security, a response, a grant or the product event handler.
                    page.evaluate(
                        "window.addEventListener('beforeprint', () => { document.documentElement.dataset.observedPrint = 'yes'; });"
                    )
                    with page.expect_response(
                        lambda r: r.url.endswith("/print-permission/")
                    ) as event:
                        page.get_by_role("button", name="طباعة هذه النسخة", exact=True).click()
                    self.assertEqual(event.value.status, 200)
                    expect(page.locator("html")).to_have_attribute("data-observed-print", "yes")
                    printed = page.pdf(path=str(OUT / proof["printed_pdf"]), print_background=True)
                    self.assertTrue(printed.startswith(b"%PDF-"))
                    self.assertGreater(len(printed), 1000)
                    proof["native_beforeprint_observed"] = True
                    proof["printed_pdf_sha256"] = sha256(printed).hexdigest()
                    grant = self.reader_authority.grants.pop("PRINT")
                    with page.expect_response(
                        lambda r: r.url.endswith("/print-permission/")
                    ) as event:
                        page.get_by_role("button", name="طباعة هذه النسخة", exact=True).click()
                    self.assertEqual(event.value.status, 404)
                    expect(page.locator("#print-content")).to_be_empty()
                    expect(page.locator("#reader-tool-status")).to_contain_text(
                        "تعذرت طباعة النسخة"
                    )
                    self.reader_authority.grants["PRINT"] = grant
                    proof["observed_statuses"]["revoked_print_control"] = 404

                    response = publisher.goto(origin + "/casework/staff/login/")
                    self.assertEqual(response.status, 200)
                    publisher.locator("#credential").fill(CREDENTIALS["publisher"])
                    self.submit(
                        publisher, publisher.get_by_role("button", name="دخول المكتب", exact=True)
                    )
                    self.submit(
                        publisher,
                        publisher.get_by_role(
                            "button", name=self.receipt["public_ref"], exact=True
                        ),
                    )
                    self.submit(
                        publisher,
                        publisher.get_by_role("button", name="نسخة النشر التجريبية", exact=True),
                    )
                    form = publisher.locator(
                        f"#publication-edition-{self.publication.pk} form"
                    ).filter(has=publisher.locator('input[name="action"][value="pub_withdraw"]'))
                    self.assertEqual(form.count(), 1)
                    form.locator('[name="confirm"]').check()
                    self.submit(
                        publisher, form.get_by_role("button", name="سحب النسخة", exact=True)
                    )

                    response = page.goto(origin + "/library-preview/reading/saved/")
                    self.assertEqual(response.status, 200)
                    expect(page.locator("#saved-references article p")).to_contain_text(
                        "لم يعد متاحًا الآن"
                    )
                    expect(page.locator("#saved-references a")).to_have_count(0)
                    self.assertNotIn(
                        self.publication.title, page.locator("#saved-references").inner_text()
                    )
                    self.capture(page, "withdrawn-reference", proof)
                    page.get_by_role("button", name="حذف هذا المرجع من الجهاز", exact=True).click()
                    expect(page.locator("#saved-references article")).to_have_count(0)
                    self.assertIsNone(page.evaluate("key => localStorage.getItem(key)", KEY))
                    for tail in ("", "share-link/", "print/", "download/"):
                        response = page.request.get(origin + tools_url + tail)
                        self.assertEqual(response.status, 404)
                        proof["observed_statuses"]["withdrawn_" + (tail.strip("/") or "reader")] = (
                            response.status
                        )
                    self.assertFalse(proof["external_requests"])
                    self.assertFalse(proof["page_errors"])
                    proof["browser_version"] = browser.version
                    proof["status"] = "PASS"
                finally:
                    for name, context in contexts:
                        trace = "trace.zip" if name == "public" else f"trace-{name}.zip"
                        context.tracing.stop(path=str(OUT / trace))
                        proof["traces"].append(trace)
                        context.close()
                    browser.close()
        except Exception as exc:
            proof["error"] = type(exc).__name__
            raise
        finally:
            (OUT / "result.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
