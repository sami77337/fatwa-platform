"""Optional real-browser checks; run against `python -m apps.editorial_followup`.

Uses Playwright installed in the local test environment only, not an app dependency.
Run from repository root: python tests/editorial_followup/browser_smoke.py
"""

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8016"
DESK = BASE + "/dev/editorial-followup"


def main():
    output = Path(".local/editorial-followup")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def layout():
            assert page.locator("html").get_attribute("dir") == "rtl"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("h1").count() == 1

        page.goto(DESK)
        expect(page.locator(".case-card")).to_have_count(17)
        layout()
        page.keyboard.press("Tab")
        expect(page.locator(".skip-link")).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator("#main-content")).to_be_focused()
        page.locator("#reason").select_option("missing_receipt")
        page.locator("#batch").select_option("synthetic-csv")
        page.locator("#status").select_option("blocked")
        page.get_by_role("button", name="تطبيق التصفية").focus()
        page.keyboard.press("Enter")
        expect(page.locator(".case-card")).to_have_count(2)
        page.locator(".case-card h3 a").first.click()
        expect(page.locator("h1")).to_contain_text("batch-synthetic-csv-2")
        assert page.locator('a[rel="prev"]').count() == 0
        page.locator('a[rel="next"]').click()
        expect(page.locator("h1")).to_contain_text("batch-synthetic-csv-4")
        assert parse_qs(urlsplit(page.url).query) == {
            "reason": ["missing_receipt"],
            "batch": ["synthetic-csv"],
            "status": ["blocked"],
        }
        assert page.locator('a[rel="next"]').count() == 0
        page.locator('a[rel="prev"]').click()
        expect(page.locator("h1")).to_contain_text("batch-synthetic-csv-2")
        page.get_by_role("link", name="العودة إلى النتائج المصفاة").click()
        expect(page.locator(".case-card")).to_have_count(2)
        page.screenshot(path=str(output / "desktop.png"))

        page.goto(DESK + "/history")
        target = page.get_by_role("link", name="فحص الهوية والدليل الدقيق للإحالة 1", exact=True)
        target.click()
        assert urlsplit(page.url).path == "/dev/reference-triage/history"
        assert urlsplit(page.url).fragment == "reference-1"
        expect(page.locator("#reference-1")).to_be_visible()
        page.goto(DESK + "/batch-synthetic-csv-1")
        # Real fixture includes combining characters, leading/trailing spaces and CRLF.
        expected_text = "  سُؤَالٌ اصطناعي\r\nبسطرٍ وتشكيل e\u0301  "
        assert (
            page.locator("#record-heading").locator("..").locator("pre code").text_content()
            == expected_text
        )

        for width in (360, 320):
            page.set_viewport_size({"width": width, "height": 800})
            for path in ("", "/history", "/batch-synthetic-jsonl-3", "/batch-synthetic-json-4"):
                page.goto(DESK + path)
                layout()
        page.goto(DESK + "/batch-synthetic-jsonl-3")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        page.goto(DESK + "?batch=synthetic-malformed")
        expect(page.locator("#batch-errors-heading").locator("..")).to_contain_text(
            "MALFORMED_INPUT"
        )
        expect(page.locator(".case-card")).to_have_count(0)
        assert context.request.post(DESK).status == 405
        assert context.request.head(DESK).status == 200
        assert not errors, errors
        browser.close()
    print(
        "PASS: desktop RTL, keyboard skip/filter, combined filters, previous/next/return, exact reference link, Arabic CRLF, 360px/320px no overflow, batch failure, GET/HEAD-only"
    )


if __name__ == "__main__":
    main()
