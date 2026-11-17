"""Real Chromium smoke for the local transcript UI; synthetic and database-free."""

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import ZipFile

from tests.fast8_transcript_queue.test_services import encode, segments


def main():
    from playwright.sync_api import sync_playwright

    executable = (
        os.environ.get("CHROME_BIN") or shutil.which("chromium") or shutil.which("google-chrome")
    )
    if not executable:
        raise RuntimeError("Chromium is required; browser check was not run")
    output = Path(".local/qa/transcript-workbench")
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    rows = segments()
    rows[1]["start_ms"] = 1000  # Deliberate repairable overlap.
    raw = encode(rows)
    env = dict(os.environ, FATWA_PRODUCTION="0")
    results = []
    with (output / "server.log").open("w") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "apps.fast8_transcript_queue.workbench", "--port", str(port)],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("local server stopped")
                try:
                    with urlopen(origin + "/transcripts/", timeout=1) as response:
                        if response.status == 200:
                            break
                except URLError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("local server not ready")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=executable, headless=True, args=["--no-sandbox"]
                )
                for width, height in ((320, 780), (1280, 900)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    errors, external = [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "request",
                        lambda request: (
                            external.append(request.url)
                            if not request.url.startswith(origin + "/")
                            else None
                        ),
                    )
                    response = page.goto(origin + "/transcripts/")
                    assert response.status == 200
                    assert "no-store" in response.headers["cache-control"]
                    page.locator("#transcript").set_input_files(
                        {
                            "name": "synthetic.json",
                            "mimeType": "application/json",
                            "buffer": raw,
                        }
                    )
                    page.locator('[name="synthetic_only"]').check()
                    page.get_by_role("button", name="استيراد ومعاينة").click()
                    page.wait_for_load_state("domcontentloaded")
                    assert page.get_by_text("تداخل بين مقطعين", exact=False).count() == 1
                    assert page.get_by_role("button", name="تنزيل الحزمة ZIP").count() == 0
                    page.locator("#segment").select_option("1")
                    page.get_by_role("button", name="عرض المقطع").click()
                    page.wait_for_load_state("domcontentloaded")
                    page.locator("#start").fill("1017")
                    page.get_by_role("button", name="حفظ التعديل في المراجعة").click()
                    page.wait_for_load_state("domcontentloaded")
                    assert page.locator("html").get_attribute("dir") == "rtl"
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    with page.expect_download() as download_event:
                        page.get_by_role("button", name="تنزيل الحزمة ZIP").click()
                    download = download_event.value
                    saved = output / f"review-{width}.zip"
                    download.save_as(saved)
                    with ZipFile(io.BytesIO(saved.read_bytes())) as archive:
                        assert archive.read("original.json") == raw
                        reviewed = json.loads(archive.read("reviewed.json"))
                        assert reviewed["items"][0]["text"] == rows[0]["text"]
                        assert reviewed["items"][1]["start_ms"] == 1017
                        manifest = json.loads(archive.read("manifest.json"))
                        assert manifest["case_binding"] == "NOT_CONNECTED"
                    page.screenshot(path=str(output / f"review-{width}.png"), full_page=True)
                    assert not errors and not external
                    results.append(
                        {
                            "viewport": [width, height],
                            "status": "PASS",
                            "page_errors": len(errors),
                            "external_requests": len(external),
                        }
                    )
                    context.close()
                version = browser.version
                browser.close()
            result = {
                "status": "PASS",
                "browser": version,
                "viewports": results,
                "case_binding": "NOT_CONNECTED",
                "deployment": "NOT_DEPLOYED",
            }
            (output / "browser-result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    main()
