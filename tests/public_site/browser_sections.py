"""Real Chromium section journey; disposable section_fixture database on port 8040."""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    base = "http://127.0.0.1:8040"
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
            link = page.get_by_role("link", name="تصفح عناوين: باب أول اصطناعي", exact=True)
            link.focus()
            link.press("Enter")
            assert page.get_by_label("الباب من المصدر", exact=True).input_value() == "1"
            assert page.get_by_text("عدد النتائج: 65", exact=False).count() == 1
            page.get_by_role("link", name="النتائج التالية", exact=True).click()
            assert parse_qs(urlsplit(page.url).query)["root"] == ["1"]
            assert page.get_by_text("عرض النتائج 31–60", exact=False).count() == 1
            page.get_by_role("link", name="النتائج التالية", exact=True).click()
            assert page.get_by_text("عرض النتائج 61–65", exact=False).count() == 1
            page.get_by_role("link", name="فرع خامس", exact=True).click()
            assert urlsplit(page.url).path == "/fiqh/nodes/65"
            page.go_back()
            page.get_by_label("كلمة أو عبارة من العنوان").fill("عنوان مشترك")
            page.get_by_role("button", name="ابحث في الفهرس").click()
            assert "offset" not in parse_qs(urlsplit(page.url).query)
            assert page.get_by_text("عدد النتائج: 61", exact=False).count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("html").get_attribute("dir") == "rtl"
            assert page.locator('link[rel="canonical"], meta[property^="og:"]').count() == 0
            response = page.request.get(page.url)
            assert response.headers["x-robots-tag"] == "noindex, nosnippet"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
            page.screenshot(path=str(output / f"sections-{width}.png"), full_page=True)
            page.get_by_role("link", name="العودة إلى جميع أبواب المصدر", exact=True).click()
            assert "root" not in parse_qs(urlsplit(page.url).query)
            assert page.get_by_text("عدد النتائج: 62", exact=False).count() == 1
            page.get_by_label("الباب من المصدر", exact=True).select_option("100")
            page.get_by_role("button", name="ابحث في الفهرس").click()
            assert page.get_by_text("عدد النتائج: 1.", exact=False).count() == 1
            assert page.get_by_role("link", name="عنوان مشترك خارج الباب", exact=True).count() == 1
            page.get_by_label("كلمة أو عبارة من العنوان").fill("")
            page.get_by_role("button", name="ابحث في الفهرس").click()
            assert page.get_by_text("عدد النتائج: 2.", exact=False).count() == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role("link", name="العودة إلى جميع أبواب المصدر", exact=True).click()
            assert page.url == base + "/"
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
