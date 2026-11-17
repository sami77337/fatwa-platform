"""Optional real Chromium check against a loopback server seeded by search_fixture.

Run with a Python environment containing Playwright (no production connection).
Writes synthetic screenshots/report to the supplied local evidence directory.
"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    base = "http://127.0.0.1:8039"
    report = {"fixture": "public-search-pagination-v1", "viewports": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        report["browser"] = browser.version
        for width, height in ((320, 780), (1280, 900)):
            context = browser.new_context(
                viewport={"width": width, "height": height}, java_script_enabled=False
            )
            page = context.new_page()
            errors, external = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: (
                    external.append(request.url) if not request.url.startswith(base + "/") else None
                ),
            )
            response = page.goto(base)
            assert response.status == 200
            page.get_by_label("كلمة أو عبارة من العنوان").fill("عنوان اصطناعي")
            page.get_by_text("خيارات البحث والمرشحات", exact=True).click()
            page.get_by_label("عمق العنوان", exact=True).select_option("2")
            page.get_by_label("العناوين الفرعية", exact=True).select_option("false")
            page.get_by_role("button", name="ابحث في الفهرس").click()
            assert page.get_by_text("عرض النتائج 1–30", exact=False).count() == 1
            next_link = page.get_by_role("link", name="النتائج التالية", exact=True)
            next_link.focus()
            next_link.press("Enter")
            assert page.get_by_text("عرض النتائج 31–60", exact=False).count() == 1
            assert parse_qs(urlsplit(page.url).query) == {
                "q": ["عنوان اصطناعي"],
                "mode": ["normalized"],
                "depth": ["2"],
                "has_children": ["false"],
                "offset": ["30"],
            }
            assert page.locator('meta[name="robots"]').get_attribute("content") == "noindex"
            assert page.locator('link[rel="canonical"], meta[property^="og:"]').count() == 0
            headers = page.request.get(page.url).headers
            assert headers["cache-control"] == "no-store"
            assert headers["referrer-policy"] == "no-referrer"
            assert headers["x-robots-tag"] == "noindex, nosnippet"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("html").get_attribute("dir") == "rtl"
            page.screenshot(path=str(output / f"search-{width}.png"), full_page=True)
            page.get_by_role("link", name="النتائج التالية", exact=True).click()
            assert page.get_by_text("عرض النتائج 61–61", exact=False).count() == 1
            assert page.get_by_role("link", name="النتائج التالية", exact=True).count() == 0
            page.get_by_role("link", name="عُنْوَانٌ اصطناعي 062", exact=True).click()
            assert urlsplit(page.url).path == "/fiqh/nodes/62"
            assert page.get_by_text("جزء اصطناعي", exact=False).count() >= 1
            page.go_back()
            page.get_by_role("link", name="النتائج السابقة", exact=True).click()
            assert page.get_by_text("عرض النتائج 31–60", exact=False).count() == 1
            page.get_by_label("كلمة أو عبارة من العنوان").fill("غيرموجود")
            page.get_by_role("button", name="ابحث في الفهرس").click()
            assert "offset" not in parse_qs(urlsplit(page.url).query)
            assert page.get_by_text("لا توجد عناوين مطابقة", exact=False).count() == 1
            page.get_by_role("link", name="مسح البحث والمرشحات", exact=True).click()
            assert page.url == base + "/"
            assert not errors and not external and not context.cookies()
            report["viewports"].append(
                {
                    "width": width,
                    "height": height,
                    "javascript": False,
                    "result": "PASS",
                    "external_requests": len(external),
                    "page_errors": len(errors),
                    "cookies": 0,
                }
            )
            context.close()
        browser.close()
    (output / "browser-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run(Path(sys.argv[1]))
