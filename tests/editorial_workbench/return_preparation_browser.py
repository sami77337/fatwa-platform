"""Scoped hosted Chrome acceptance; synthetic preparation never authorizes delivery."""

import json
import os
import secrets
import subprocess
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, make_server

from django.core.wsgi import get_wsgi_application
from playwright.sync_api import sync_playwright

from apps.fast9_case_source_join.answer_drafts import AUTHOR, REVIEWER
from apps.fast9_case_source_join.draft_source_review import inspect_draft_source
from apps.fast9_case_source_join.return_handoff import read_return_candidate
from apps.fast9_case_source_join.source_history import sample_source_events
from apps.fast9_case_source_join.source_journal import (
    acknowledge_review,
    append_source_event,
    history_digest,
    read_case_review,
    record_draft_note,
    save_answer_draft,
)

SETTINGS = "apps.editorial_workbench.reviewer_settings"
URL = "/review/author/return-preparation/"
EVIDENCE = Path(".local/qa/fast9-integrated/return-preparation-browser.json")
VIEWPORTS = ({"width": 320, "height": 780}, {"width": 1280, "height": 900})
# Human-written training prose, deliberately including CRLF, marks, whitespace and markup.
TITLE = "  عُنوانٌ تدريبيٌّ <عنوان> & نهاية.  "
BODY = "  نَصٌّ تدريبيٌّ <مثال> & فقط.\r\nكلمةٌ ثانية\t ونهايةٌ محفوظة.  "
LIMIT = 24
TIMEOUT = 10_000


class AcceptanceFailure(AssertionError):
    """Contains only a fixed, non-sensitive assertion code."""


def require(condition, message):
    if not condition:
        raise AcceptanceFailure(message)


def disk_state(directory):
    return {
        p.relative_to(directory).as_posix(): {
            "sha256": sha256(p.read_bytes()).hexdigest(),
            "mtime_ns": p.stat().st_mtime_ns,
        }
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def seed_fixture(directory):
    """Only public journal APIs, fixed fixture actors and technical submit/confirm."""
    (event,) = sample_source_events("intake-7", "received")
    append_source_event(directory, event, synthetic_fixtures_only=True)
    state = read_case_review(directory, synthetic_fixtures_only=True)
    source_digest = history_digest(state.events)
    intake = inspect_draft_source("intake-7", 1, state.events, synthetic_fixtures_only=True)
    acknowledge_review(
        directory,
        reviewer=REVIEWER,
        count=len(state.events),
        source_digest=source_digest,
        draft_digest=intake.draft_revision_sha256,
        reply_digest=state.reply_digest,
        synthetic_fixtures_only=True,
    )
    draft = save_answer_draft(
        directory,
        author=AUTHOR,
        base_revision=0,
        count=len(state.events),
        source_digest=source_digest,
        reply_digest=state.reply_digest,
        title=TITLE,
        body=BODY,
        evidence_seen=True,
        synthetic_fixtures_only=True,
    )
    for index, (actor, action) in enumerate(((AUTHOR, "submit"), (REVIEWER, "confirm"))):
        record_draft_note(
            directory,
            reviewer=actor,
            action=action,
            text="",
            revision=draft.revision,
            draft_digest=draft.digest,
            note_count=index,
            synthetic_fixtures_only=True,
        )
    candidate = read_return_candidate(directory, synthetic_fixtures_only=True)
    require(candidate.blockers == (), "fixture_preparation_blockers")
    require(candidate.technical_review_current, "fixture_technical_review_missing")
    require(candidate.draft.title == TITLE and candidate.draft.body == BODY, "fixture_text_changed")
    require(len(disk_state(directory)) == 1, "fixture_unexpected_files")
    return candidate


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *_args):
        # Do not log request paths, credentials, responses or fixture text.
        pass

    def handle(self):
        self.connection.settimeout(TIMEOUT / 1000)
        super().handle()


@contextmanager
def local_server():
    with make_server("127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            require(thread.is_alive(), "server_startup_failed")
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            require(not thread.is_alive(), "server_shutdown_timeout")


def safe_headers(response):
    require(response is not None and response.status == 200, "safe_response_status")
    headers = response.headers
    require(headers.get("cache-control") == "no-store", "safe_response_cache")
    require(
        headers.get("content-security-policy")
        == "default-src 'none'; style-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'",
        "safe_response_csp",
    )


def form_login(page, origin, role, credential):
    login, landing = {
        "author": ("/review/author/login/", "/review/author/queue/"),
        "reviewer": ("/review/login/", "/review/"),
        "operator": ("/review/operations/login/", "/review/operations/outbox/"),
    }[role]
    safe_headers(page.goto(origin + login))
    # Real browser form posts the rendered CSRF field and receives its own cookie jar.
    require(page.locator('input[name="csrfmiddlewaretoken"]').count() == 1, "login_csrf_missing")
    page.locator('input[name="token"]').fill(credential)
    with page.expect_navigation(wait_until="load", timeout=TIMEOUT) as navigation:
        page.locator('button[type="submit"]').click()
    response = navigation.value
    require(response is not None and response.status == 200, "login_failed")
    require(page.url == origin + landing, "login_failed")
    require(page.locator('input[name="token"]').count() == 0, "login_failed")


def keyboard_to(page, locator):
    for _ in range(30):
        page.keyboard.press("Tab")
        if locator.evaluate("element => element === document.activeElement"):
            return
    raise AcceptanceFailure("keyboard_target_unreachable")


def check_view(page, context, origin, role, viewport):
    page.set_viewport_size(viewport)
    safe_headers(page.goto(origin + URL))
    require(page.locator("html").get_attribute("lang") == "ar", "arabic_language_missing")
    require(page.locator("html").get_attribute("dir") == "rtl", "rtl_missing")
    require(page.evaluate("getComputedStyle(document.body).direction") == "rtl", "rtl_style")
    require(page.title() == "تحضير إرجاع الجواب", "document_title")
    saved = page.locator('section[aria-labelledby="answer-heading"] pre')
    require(saved.count() == 2, "saved_text_elements")
    require(saved.nth(0).text_content() == TITLE, "exact_title_changed")
    require(saved.nth(1).text_content() == BODY, "exact_body_changed")
    for index in range(saved.count()):
        wrapper = saved.nth(index)
        require(wrapper.locator(":scope > code").count() == 1, "exact_code_wrapper_missing")
        require(wrapper.locator("*").count() == 1, "markup_not_escaped")
    require(
        page.get_by_text("اكتملت متطلبات التحضير لهذه النسخة.", exact=True).is_visible(),
        "preparation_blockers_present",
    )
    require(
        page.get_by_text("بانتظار اعتماد المفتي عبر جهة تحقق موثوقة.", exact=True).is_visible(),
        "trusted_approval_boundary_missing",
    )
    require(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "overflow")
    # The first actual Tab exposes the skip link; Enter focuses the main landmark.
    page.keyboard.press("Tab")
    skip = page.locator(".skip-link")
    require(skip.evaluate("element => element === document.activeElement"), "skip_link_focus")
    require(skip.is_visible(), "skip_link_hidden")
    require(
        skip.evaluate("element => element.getBoundingClientRect().top >= 0"), "skip_link_offscreen"
    )
    page.keyboard.press("Enter")
    require(page.locator("#main").evaluate("el => el === document.activeElement"), "main_focus")
    # A normal GET form submission initially refuses an implicit split.
    page.locator("#max-chars").fill(str(LIMIT))
    submit = page.locator('form[method="get"] button[type="submit"]')
    with page.expect_navigation(wait_until="load", timeout=TIMEOUT) as navigation:
        submit.click()
    safe_headers(navigation.value)
    require(
        page.get_by_text(
            "يتطلب تقسيم النص اختيارًا صريحًا قبل عرض الأجزاء.", exact=True
        ).is_visible(),
        "implicit_split_not_refused",
    )
    parts = page.locator("ol.timeline pre.exact-text")
    require(parts.count() == 0, "implicit_split_rendered")
    # Reach and activate the checkbox and submit with keyboard only.
    checkbox = page.locator("#split-choice")
    keyboard_to(page, checkbox)
    page.keyboard.press("Space")
    require(checkbox.is_checked(), "keyboard_checkbox_failed")
    keyboard_to(page, submit)
    with page.expect_navigation(wait_until="load", timeout=TIMEOUT) as navigation:
        page.keyboard.press("Enter")
    safe_headers(navigation.value)
    texts = parts.all_text_contents()
    require(len(texts) > 1 and "".join(texts) == BODY, "segments_not_lossless")
    require(all(0 < len(text) <= LIMIT for text in texts), "segment_limit_exceeded")
    require(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "preview_overflow")
    # APIRequestContext is explicitly pinned to this known local URL, without redirects;
    # browser requests are separately enforced by the context route below.
    safe_headers(context.request.head(page.url, max_redirects=0, timeout=TIMEOUT))
    return {
        "role": role,
        "viewport": viewport,
        "checks": [
            "arabic_rtl",
            "no_overflow",
            "exact_title_body_crlf_whitespace_markup",
            "preparation_ready_approval_awaited",
            "keyboard_skip_main",
            "explicit_split_required",
            "keyboard_checkbox_submit",
            "lossless_bounded_segments",
            "get_head_no_store_csp",
        ],
        "segments": len(texts),
        "limit": LIMIT,
    }


def run(receipt):
    require(os.environ.get("DJANGO_SETTINGS_MODULE") == SETTINGS, "wrong_settings_profile")
    require(os.environ.get("FATWA_PRODUCTION", "0") == "0", "production_forbidden")
    executable = os.environ.get("FATWA_FASTBUILD_BROWSER", "")
    require(
        executable == "/usr/bin/google-chrome" and Path(executable).is_file(),
        "system_chrome_missing",
    )
    if os.environ.get("GITHUB_SHA"):
        require(receipt["sha"] == os.environ["GITHUB_SHA"], "checkout_sha_mismatch")
    tokens = {role: secrets.token_hex(32) for role in ("author", "reviewer", "operator")}
    with TemporaryDirectory(prefix="fatwa-browser-synthetic-") as tmp, ExitStack() as stack:
        directory = Path(tmp)
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "FATWA_SYNTHETIC_SOURCE_JOURNAL_DIR": str(directory),
                    **{
                        f"FATWA_SYNTHETIC_{role.upper()}_TOKEN_SHA256": sha256(
                            token.encode()
                        ).hexdigest()
                        for role, token in tokens.items()
                    },
                },
            )
        )
        database = stack.enter_context(
            patch(
                "django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection",
                side_effect=RuntimeError("postgres_access_forbidden"),
            )
        )
        receipt["stage"] = "fixture_seeding"
        seed_fixture(directory)
        before = disk_state(directory)
        receipt["seeded_files"] = before
        receipt["stage"] = "server_startup"
        origin = stack.enter_context(local_server())
        receipt["stage"] = "browser_startup"
        driver = stack.enter_context(sync_playwright())
        browser = driver.chromium.launch(
            executable_path=executable, chromium_sandbox=True, timeout=TIMEOUT
        )
        stack.callback(browser.close)
        receipt["browser"] = browser.version
        contexts = {}
        pages = {}

        def local_only(route):
            url = urlsplit(route.request.url)
            if f"{url.scheme}://{url.netloc}" != origin:
                receipt["unexpected_network_requests"] += 1
                route.abort()
            else:
                route.continue_()

        for role in ("anonymous", "author", "reviewer", "operator"):
            context = browser.new_context(viewport=VIEWPORTS[0], service_workers="block")
            stack.callback(context.close)
            context.set_default_timeout(TIMEOUT)
            context.set_default_navigation_timeout(TIMEOUT)
            context.route("**/*", local_only)
            page = context.new_page()
            page.on(
                "pageerror",
                lambda _error: receipt.__setitem__("page_errors", receipt["page_errors"] + 1),
            )
            contexts[role], pages[role] = context, page
            if role != "anonymous":
                receipt["stage"] = f"{role}_form_login"
                form_login(page, origin, role, tokens[role])
        receipt["checks"].append("separate_context_real_csrf_form_logins")
        for role in ("anonymous", "operator"):
            receipt["stage"] = f"{role}_denial"
            page = pages[role]
            response = page.goto(origin + URL)
            safe_headers(response)
            require(page.url == origin + "/review/author/login/", "unauthorized_not_redirected")
            require(page.locator("pre.exact-text").count() == 0, "unauthorized_draft_disclosure")
            text = page.locator("body").text_content()
            require(
                TITLE not in text and BODY not in text and "intake-7" not in text,
                "unauthorized_disclosure",
            )
            head = contexts[role].request.head(origin + URL, max_redirects=0, timeout=TIMEOUT)
            require(
                head.status == 302 and head.headers.get("location") == "/review/author/login/",
                "denied_head",
            )
            require(head.headers.get("cache-control") == "no-store", "denied_head_cache")
            require(
                "frame-ancestors 'none'" in head.headers.get("content-security-policy", ""),
                "denied_head_csp",
            )
            receipt["checks"].append(f"{role}_get_head_denied_without_disclosure")
        for role in ("author", "reviewer"):
            for viewport in VIEWPORTS:
                receipt["stage"] = f"{role}_{viewport['width']}_preparation"
                receipt["views"].append(
                    check_view(pages[role], contexts[role], origin, role, viewport)
                )
                require(
                    disk_state(directory) == before,
                    "read_preview_changed_journal_or_created_outbox",
                )
        receipt["stage"] = "final_invariants"
        require(database.call_count == 0, "database_access_attempted")
        require(receipt["unexpected_network_requests"] == 0, "unexpected_network_request")
        require(receipt["page_errors"] == 0, "browser_page_error")
        require(disk_state(directory) == before, "read_changed_files")
        receipt["checks"].extend(
            ["journal_hashes_mtime_unchanged_no_outbox", "zero_database_access"]
        )
        receipt["final_files"] = disk_state(directory)
        receipt["journal_unchanged"] = True
    receipt["stage"] = "complete"


def main():
    receipt = {
        "schema": "return-preparation-browser.v1",
        "result": "FAIL",
        "stage": "initialization",
        "sha": None,
        "browser": None,
        "viewports": list(VIEWPORTS),
        "checks": [],
        "views": [],
        "unexpected_network_requests": 0,
        "page_errors": 0,
        "journal_unchanged": False,
        "scope": "synthetic_preparation_access_preview_only",
    }
    try:
        receipt["sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        run(receipt)
        receipt["result"] = "PASS"
    except Exception as error:
        # Playwright exceptions can contain input/HTML. Never serialize them or a traceback.
        receipt["failure"] = {
            "stage": receipt["stage"],
            "message": (
                str(error)
                if isinstance(error, AcceptanceFailure)
                else "Acceptance failed; no sensitive diagnostics captured."
            ),
            "type": type(error).__name__,
        }
    finally:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "result": receipt["result"],
                "sha": receipt["sha"],
                "stage": receipt["stage"],
                "evidence": str(EVIDENCE),
                "browser": receipt["browser"],
                "views": receipt["views"],
                "unexpected_network_requests": receipt["unexpected_network_requests"],
                "page_errors": receipt["page_errors"],
                "journal_unchanged": receipt["journal_unchanged"],
            }
        )
    )
    return 0 if receipt["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
