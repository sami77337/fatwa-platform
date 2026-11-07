"""Run the four fixed case-source review examples in sandboxed Chrome."""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server

from django.core.wsgi import get_wsgi_application
from playwright.sync_api import expect, sync_playwright

from apps.fast9_case_source_join.source_history import CORRECTION_BODIES, source_receipt


def main():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    initial = source_receipt("intake-7").body_utf8.decode()
    correction = CORRECTION_BODIES[0].decode()
    samples = (
        ("received", "SOURCE_TEXT_UNCHANGED", ("received",), initial),
        ("corrected", "SOURCE_TEXT_CHANGED_REVIEW_NEEDED", ("received", "corrected"), correction),
        ("deleted", "SOURCE_DELETED_REVIEW_NEEDED", ("received", "corrected", "deleted"), None),
        (
            "restored",
            "SOURCE_TEXT_CHANGED_REVIEW_NEEDED",
            ("received", "corrected", "corrected"),
            initial,
        ),
    )
    rows = []
    blocked = []
    errors = []
    with make_server("127.0.0.1", 0, get_wsgi_application()) as server:
        origin = f"http://127.0.0.1:{server.server_port}"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as driver:
                browser = driver.chromium.launch(
                    executable_path=os.environ["FATWA_FASTBUILD_BROWSER"], chromium_sandbox=True
                )
                version = browser.version
                context = browser.new_context(viewport={"width": 1280, "height": 900})

                def local_only(route):
                    url = urlsplit(route.request.url)
                    if f"{url.scheme}://{url.netloc}" != origin:
                        blocked.append(url.netloc)
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", local_only)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                detail = "/dev/editorial-workbench/intake-7"
                response = page.goto(origin + detail)
                assert response is not None and response.status == 200
                page.locator("#source-review-link").click()
                for sample, status, kinds, latest in samples:
                    if sample != "received":
                        link = page.locator(f'#source-review-samples a[href$="sample={sample}"]')
                        link.focus()
                        page.keyboard.press("Enter")
                    state = page.locator("#source-review-status")
                    expect(state).to_be_visible()
                    expect(state).to_have_attribute("data-status", status)
                    assert page.locator("#source-review-original code").text_content() == initial
                    events = page.locator("#source-review-timeline > li[data-kind]")
                    expect(events).to_have_count(len(kinds))
                    assert (
                        tuple(events.nth(i).get_attribute("data-kind") for i in range(len(kinds)))
                        == kinds
                    )
                    text = page.locator("#source-review-latest code")
                    if latest is None:
                        expect(text).to_have_count(0)
                        expect(page.locator("#source-review-latest")).to_be_visible()
                    else:
                        assert text.text_content() == latest
                    rows.append({"sample": sample, "status": status, "events": list(kinds)})
                page.set_viewport_size({"width": 320, "height": 780})
                expect(page.locator("#source-review-status")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                context.close()
                browser.close()
        finally:
            server.shutdown()
            thread.join()
    assert not blocked and not errors, (blocked, errors)
    receipt = {
        "sha": head,
        "browser": version,
        "case": "intake-7",
        "original_question_sha256": hashlib.sha256(initial.encode()).hexdigest(),
        "samples": rows,
        "mobile_width": 320,
        "unexpected_network_requests": len(blocked),
        "page_errors": len(errors),
        "result": "PASS",
    }
    Path("case-source-browser.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print("PASS: source receipt, correction, deletion and restoration on the current draft")


if __name__ == "__main__":
    main()
