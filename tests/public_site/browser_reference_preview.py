"""Chromium reference preview/return journey using disposable section_fixture on 8041."""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    base = "http://127.0.0.1:8041"
    report = {"fixture": "public-source-sections-v1", "viewports": []}
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
            page.goto(base)
            page.get_by_label("الباب من المصدر", exact=True).select_option("1")
            page.get_by_label("كلمة أو عبارة من العنوان").fill("عنوان مشترك")
            page.get_by_text("خيارات البحث والمرشحات", exact=True).click()
            page.get_by_label("عمق العنوان", exact=True).select_option("2")
            page.get_by_label("العناوين الفرعية", exact=True).select_option("false")
            page.get_by_role("button", name="ابحث في الفهرس").click()
            page.get_by_role("link", name="النتائج التالية", exact=True).click()
            expected = parse_qs(urlsplit(page.url).query)
            preview = page.get_by_role("link", name="معاينة إحالة: عنوان مشترك 032", exact=True)
            preview.focus()
            preview.press("Enter")
            assert urlsplit(page.url).fragment == "reference-title"
            assert parse_qs(urlsplit(page.url).query) == {**expected, "heading": ["32"]}
            assert page.get_by_role("heading", name="إحالة العنوان ومساره", exact=True).count() == 1
            assert (
                page.get_by_role("navigation", name="مسار العنوان في المصدر", exact=True)
                .get_by_role("listitem")
                .count()
                == 2
            )
            assert "الصفحة المطبوعة: 32" in page.locator("blockquote").inner_text()
            clean = page.get_by_role(
                "link", name="فتح تفاصيل العنوان ورابطه", exact=True
            ).get_attribute("href")
            assert set(parse_qs(urlsplit(clean).query)) == {"basic", "edition"}
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("html").get_attribute("dir") == "rtl"
            assert page.locator('link[rel="canonical"], meta[property^="og:"]').count() == 0
            response = page.request.get(page.url)
            for key, value in {
                "x-robots-tag": "noindex, nosnippet",
                "cache-control": "no-store",
                "referrer-policy": "no-referrer",
            }.items():
                assert response.headers[key] == value
            page.screenshot(path=str(output / f"reference-preview-{width}.png"), full_page=True)
            page.get_by_role("link", name="فتح تفاصيل العنوان ورابطه", exact=True).click()
            assert urlsplit(page.url).path == "/fiqh/nodes/32"
            page.go_back()
            page.get_by_role("link", name="العودة إلى النتائج نفسها", exact=True).click()
            assert parse_qs(urlsplit(page.url).query) == expected
            assert page.get_by_role("heading", name="إحالة العنوان ومساره", exact=True).count() == 0
            assert page.get_by_text("عرض النتائج 31–60", exact=False).count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors and not external and not context.cookies()
            report["viewports"].append(
                {
                    "width": width,
                    "height": height,
                    "javascript": False,
                    "result": "PASS",
                    "external_requests": 0,
                    "page_errors": 0,
                    "cookies": 0,
                }
            )
            context.close()
        browser.close()
    (output / "browser-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run(Path(sys.argv[1]))
