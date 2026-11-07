"""Hosted acceptance of the saved synthetic review across two separate web processes."""

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from apps.fast9_case_source_join.source_history import CORRECTION_BODIES, source_receipt

ORIGIN = "http://127.0.0.1:8016"
DETAIL = ORIGIN + "/dev/editorial-workbench/intake-7"
JOURNAL = DETAIL + "/source-review/journal"


def disk_state(directory):
    return {
        p.name: (sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in directory.iterdir()
    }


@contextmanager
def server(env):
    # This development launcher serves the project's URL configuration without DB preflight.
    with socket.socket() as claim:
        claim.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        claim.bind(("127.0.0.1", 8016))
    proc = subprocess.Popen([sys.executable, "-B", "-m", "apps.editorial_followup"], env=env)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("preview_process_exited")
            try:
                with urlopen(DETAIL, timeout=1) as response:
                    if response.status == 200:
                        break
            except URLError:
                time.sleep(0.1)
        else:
            raise TimeoutError("preview_startup_timeout")
        yield proc.pid
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def record(env, sample):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "tools.fast9_case_source_join.journal",
            "--synthetic-fixtures-only",
            "--case-key",
            "intake-7",
            "record",
            sample,
        ],
        env=env,
        stdout=subprocess.PIPE,
        check=True,
        timeout=20,
    )
    return json.loads(result.stdout)


def main():
    checked = []
    unexpected = []
    errors = []
    original = source_receipt("intake-7").body_utf8.decode()
    with TemporaryDirectory() as tmp, sync_playwright() as playwright:
        directory = Path(tmp)
        env = {**os.environ, "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(directory), "PGPORT": "1"}
        browser = playwright.chromium.launch(
            executable_path=os.environ["FATWA_FASTBUILD_BROWSER"], chromium_sandbox=True
        )
        ctx = browser.new_context(viewport={"width": 320, "height": 780})

        def only_local(route):
            u = urlsplit(route.request.url)
            if f"{u.scheme}://{u.netloc}" == ORIGIN:
                route.continue_()
            else:
                unexpected.append(u.netloc)
                route.abort()

        ctx.route("**/*", only_local)
        page = ctx.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def open_saved(expected_status, tip, text):
            before = disk_state(directory)
            response = page.goto(JOURNAL)
            assert response is not None and response.status == 200
            assert "no-store" in response.headers["cache-control"]
            expect(page.locator("#source-review-status")).to_have_attribute(
                "data-status", expected_status
            )
            assert page.locator("#source-journal-tip").text_content().strip() == tip
            assert page.locator("#source-review-original code").text_content() == original
            if text is None:
                expect(page.locator("#source-review-latest code")).to_have_count(0)
            else:
                assert page.locator("#source-review-latest code").text_content() == text
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert ctx.request.head(JOURNAL).status == 200 and before == disk_state(directory)
            checked.append({"status": expected_status, "tip": tip})

        with server(env) as first:
            page.goto(DETAIL)
            link = page.locator("#source-journal-link")
            link.focus()
            page.keyboard.press("Enter")
            expect(page.locator('p[role="alert"]')).to_be_visible()
            assert page.url == JOURNAL and ctx.request.get(JOURNAL).status == 404
            assert not disk_state(directory)
            record(env, "received")
            open_saved("SOURCE_TEXT_UNCHANGED", "received-intake-7", original)
            edited = record(env, "corrected")
            open_saved(
                "SOURCE_TEXT_CHANGED_REVIEW_NEEDED", "edit-example", CORRECTION_BODIES[0].decode()
            )
        after_stop = disk_state(directory)
        with server(env) as second:
            assert first != second and disk_state(directory) == after_stop
            open_saved(
                "SOURCE_TEXT_CHANGED_REVIEW_NEEDED", "edit-example", CORRECTION_BODIES[0].decode()
            )
            assert record(env, "corrected") == edited and disk_state(directory) == after_stop
            record(env, "deleted")
            open_saved("SOURCE_DELETED_REVIEW_NEEDED", "delete-example", None)
        assert not errors and not unexpected
        receipt = {
            "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "chrome": browser.version,
            "server_pids": [first, second],
            "initial_http": 404,
            "review_states": checked,
            "reads_left_files_unchanged": True,
            "retry_unchanged": True,
            "page_errors": len(errors),
            "unexpected_network": len(unexpected),
            "viewport": 320,
            "result": "PASS",
        }
        ctx.close()
        browser.close()
    Path("source-journal-browser.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
